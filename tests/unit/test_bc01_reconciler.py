from datetime import datetime, timedelta, timezone
from copy import deepcopy
import pytest
from services.device_config_service.blast_timeout_reconciler import reconcile_once

T = datetime(2026, 10, 29, 9, 53, 18, tzinfo=timezone.utc)

class Tx:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self):
        self.snapshot = deepcopy((self.conn.trigger, self.conn.timeout, self.conn.pending, self.conn.events))
        return self
    async def __aexit__(self, typ, val, tb):
        if typ:
            self.conn.trigger, self.conn.timeout, self.conn.pending, self.conn.events = self.snapshot
        return False

class Conn:
    def __init__(self, now, started=T, value=1, timeout=1, fail=False):
        self.now, self.trigger, self.timeout, self.fail = now, {'config_value': value, 'updated_at': started}, timeout, fail
        self.pending, self.events = [], []
        self.restarted = False
    def transaction(self): return Tx(self)
    async def fetch(self, query, *args):
        if 'FROM device_config' in query and 'SELECT device_id' in query:
            return [{'device_id': 'BASE-01', 'updated_at': self.trigger['updated_at']}] if self.trigger['config_value'] == 1 else []
        raise AssertionError(query)
    async def fetchrow(self, query, *args):
        if 'FROM device_config' in query and "config_key='TriggerStart'" in query.replace(" ", ""): return self.trigger.copy()
        if 'FROM device_config' in query and "config_key='TimeOutTrigger'" in query.replace(" ", ""): return {'config_value': self.timeout} if self.timeout is not None else None
        if 'FROM devices' in query: return {'device_id': args[0]}
        raise AssertionError(query)
    async def fetchval(self, query, *args):
        assert 'clock_timestamp()' in query
        return self.now
    async def execute(self, query, *args):
        if 'INSERT INTO device_config (' in query:
            self.trigger = {'config_value': args[2], 'updated_at': self.now}
        elif 'INSERT INTO device_config_pending' in query:
            self.pending.append(args)
        elif 'INSERT INTO blast_trigger_timeout_events' in query:
            if self.fail: raise RuntimeError('database error')
            self.events.append(args)
        else: raise AssertionError(query)

class Acquire:
    def __init__(self, conn): self.conn=conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *args): return False
class Pool:
    def __init__(self, conn): self.conn=conn
    def acquire(self): return Acquire(self.conn)

@pytest.mark.asyncio
async def test_no_request_expiry_and_idempotent_retry():
    conn=Conn(T+timedelta(seconds=61))
    assert await reconcile_once(Pool(conn)) == 1
    assert conn.trigger['config_value'] == 0
    assert len(conn.pending) == len(conn.events) == 1
    assert await reconcile_once(Pool(conn)) == 0
    assert len(conn.pending) == len(conn.events) == 1

@pytest.mark.asyncio
async def test_before_deadline_and_new_start_generation():
    conn=Conn(T+timedelta(seconds=61), started=T+timedelta(seconds=50))
    assert await reconcile_once(Pool(conn)) == 0
    assert conn.trigger['config_value'] == 1

@pytest.mark.asyncio
async def test_reset_already_applied():
    conn=Conn(T+timedelta(seconds=90), value=0)
    assert await reconcile_once(Pool(conn)) == 0
    assert not conn.events

@pytest.mark.asyncio
async def test_invalid_timeout_fails_closed():
    conn=Conn(T, timeout=None)
    assert await reconcile_once(Pool(conn)) == 1
    assert conn.trigger['config_value'] == 0

@pytest.mark.asyncio
async def test_audit_failure_rolls_back_reset():
    conn=Conn(T+timedelta(seconds=61), fail=True)
    with pytest.raises(RuntimeError, match='database error'):
        await reconcile_once(Pool(conn))
    assert conn.trigger['config_value'] == 1
    assert conn.pending == [] and conn.events == []

@pytest.mark.asyncio
async def test_bad_limit_fails_before_db():
    with pytest.raises(ValueError): await reconcile_once(None, limit=0)

@pytest.mark.asyncio
async def test_keyset_scans_past_full_unexpired_batch():
    class PagingConn(Conn):
        def __init__(self):
            super().__init__(T + timedelta(seconds=61), value=0)
            self.calls = 0
        async def fetch(self, query, *args):
            self.calls += 1
            if self.calls == 1:
                return [{'device_id': 'BASE-A', 'updated_at': T},
                        {'device_id': 'BASE-B', 'updated_at': T}]
            if self.calls == 2:
                assert 'AND (updated_at, device_id) > ($2, $3)' in query
                assert args == (2, T, 'BASE-B')
                return [{'device_id': 'BASE-C', 'updated_at': T}]
            raise AssertionError('unexpected extra query')
        async def fetchrow(self, query, *args):
            if 'FROM device_config' in query and "config_key='TriggerStart'" in query.replace(' ', ''):
                return {'config_value': 0, 'updated_at': T}
            raise AssertionError(query)
    conn = PagingConn()
    assert await reconcile_once(Pool(conn), limit=2) == 0
    assert conn.calls == 2
