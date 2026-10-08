from copy import deepcopy
import pytest
from services.blast_service import reset_blast_atomic, trigger_blast_atomic
class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn
    async def __aenter__(self):
        self.snapshot = (
            deepcopy(self.conn.config),
            deepcopy(self.conn.pending),
            deepcopy(self.conn.commands),
            deepcopy(self.conn.audits),
        )
        return self
    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.conn.config, self.conn.pending, self.conn.commands, self.conn.audits = self.snapshot
        return False
class FakeConn:
    def __init__(self, fail_command=False, fail_audit=False):
        self.fail_command = fail_command
        self.fail_audit = fail_audit
        self.config = {("BASE-01", "TriggerStart"): 0, ("BASE-01", "TimeOutTrigger"): 300}
        self.pending = []
        self.commands = []
        self.audits = []
        self.last_requested_by = None
    def transaction(self):
        return FakeTransaction(self)
    async def fetchrow(self, query, *args):
        if "SELECT device_id FROM devices" in query:
            return {"device_id": args[0]} if args[0] == "BASE-01" else None
        if "INSERT INTO blast_trigger_commands" in query:
            if self.fail_command:
                raise RuntimeError("forced command insert failure")
            self.last_requested_by = args[1]
            self.commands.append((args[0], args[1]))
            return {"command_id": 42}
        raise AssertionError(query)
    async def execute(self, query, *args):
        if "INSERT INTO device_config " in query:
            self.config[(args[0], args[1])] = args[2]
            return "INSERT 0 1"
        if "INSERT INTO device_config_pending" in query:
            self.pending.append((args[0], args[1], args[2]))
            return "INSERT 0 1"
        if "INSERT INTO audit_log" in query:
            if self.fail_audit:
                raise RuntimeError("forced audit failure")
            self.audits.append(args)
            return "INSERT 0 1"
        raise AssertionError(query)
class Acquire:
    def __init__(self, conn):
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, exc_type, exc, tb):
        return False
class FakePool:
    def __init__(self, conn):
        self.conn = conn
    def acquire(self):
        return Acquire(self.conn)
@pytest.mark.asyncio
async def test_string_jwt_sub_is_bound_as_integer_and_trigger_uses_minutes():
    conn = FakeConn()
    command_id = await trigger_blast_atomic(FakePool(conn), "BASE-01", 2, "1")
    assert command_id == 42
    assert conn.last_requested_by == 1
    assert isinstance(conn.last_requested_by, int)
    assert conn.config[("BASE-01", "TriggerStart")] == 1
    assert conn.config[("BASE-01", "TimeOutTrigger")] == 2
    assert conn.audits[0][0] == 1
@pytest.mark.asyncio
async def test_command_insert_failure_rolls_back_config_pending_and_audit():
    conn = FakeConn(fail_command=True)
    with pytest.raises(RuntimeError, match="forced command insert failure"):
        await trigger_blast_atomic(FakePool(conn), "BASE-01", 2, "1")
    assert conn.config[("BASE-01", "TriggerStart")] == 0
    assert conn.config[("BASE-01", "TimeOutTrigger")] == 300
    assert conn.pending == []
    assert conn.commands == []
    assert conn.audits == []
@pytest.mark.asyncio
async def test_audit_failure_rolls_back_trigger_command_and_config():
    conn = FakeConn(fail_audit=True)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        await trigger_blast_atomic(FakePool(conn), "BASE-01", 2, "1")
    assert conn.config[("BASE-01", "TriggerStart")] == 0
    assert conn.config[("BASE-01", "TimeOutTrigger")] == 300
    assert conn.pending == []
    assert conn.commands == []
    assert conn.audits == []
@pytest.mark.asyncio
async def test_reset_sets_trigger_zero_and_keeps_timeout_in_minutes():
    conn = FakeConn()
    conn.config[("BASE-01", "TriggerStart")] = 1
    conn.config[("BASE-01", "TimeOutTrigger")] = 2
    await reset_blast_atomic(FakePool(conn), "BASE-01", "1")
    assert conn.config[("BASE-01", "TriggerStart")] == 0
    assert conn.config[("BASE-01", "TimeOutTrigger")] == 2
    assert conn.audits[0][0] == 1
