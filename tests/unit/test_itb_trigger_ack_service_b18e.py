from datetime import datetime, timezone
import pytest
from services.device_config_service.trigger_ack_service import acknowledge_trigger_start

NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)

class Conn:
    def __init__(self, sender='base', state=1, base_count=1, pending=True, acked=False):
        self.sender, self.state, self.base_count = sender, state, base_count
        self.pending, self.acked = pending, acked
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.fail_insert = False
    def transaction(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, t, e, tb):
        self.rolled_back = bool(t)
        self.committed = not t
        return False
    async def fetchrow(self, q, *args):
        if 'FROM public.devices' in q:
            return None if self.sender == 'unknown' else {'device_id':args[0], 'site_id':'SITE-1', 'device_type':self.sender}
        if 'FROM public.device_config_pending' in q:
            return ({'id':17,'config_value':self.state,'created_at':NOW,'acked_at':NOW if self.acked else None}
                    if self.pending else None)
        if 'FROM public.device_config' in q:
            return {'config_value':self.state,'updated_at':NOW}
        raise AssertionError(q)
    async def fetch(self, q, *args):
        if 'FROM public.devices' in q:
            return [{'device_id':'BASE-01'}] * self.base_count
        raise AssertionError(q)
    async def execute(self, q, *args):
        if self.fail_insert and 'INSERT INTO public.blast_trigger_acks' in q:
            raise RuntimeError('Simulated INSERT failure')
        self.executed.append((q,args))
        return 'INSERT 0 1'

class Pool:
    def __init__(self,conn): self.conn=conn
    def acquire(self): return self.conn

async def call(conn, device_id='BASE-01', role='base', trigger=1):
    return await acknowledge_trigger_start(Pool(conn), device_id=device_id, device_role=role, trigger_start=trigger)

@pytest.mark.asyncio
@pytest.mark.parametrize('value',[0,1])
async def test_base_ack_updates_acked_at(value):
    conn=Conn(state=value)
    assert await call(conn,trigger=value)
    assert len(conn.executed)==2
    assert 'UPDATE public.device_config_pending' in conn.executed[0][0]
    assert conn.executed[1][1][0]=='BASE-01'

@pytest.mark.asyncio
async def test_rover_ack_does_not_mark_base_pending_acked():
    conn=Conn(sender='rover')
    assert await call(conn,'ROVER-B1-01','rover')
    assert len(conn.executed)==1
    assert conn.executed[0][1][0]=='ROVER-B1-01'
    assert conn.executed[0][1][1]==17

@pytest.mark.asyncio
async def test_retry_does_not_update_base_pending():
    conn=Conn(acked=True)
    assert await call(conn)
    assert len(conn.executed)==1

@pytest.mark.asyncio
@pytest.mark.parametrize('kwargs',[
    {'sender':'unknown'}, {'sender':'other'}, {'sender':'rover','base_count':0},
    {'sender':'rover','base_count':2}, {'pending':False},
])
async def test_invalid_sender_or_pending_creates_rejection_only(kwargs):
    conn=Conn(**kwargs)
    assert not await call(conn, 'ROVER-B1-01', 'rover')
    assert len(conn.executed)==1
    assert 'INSERT INTO public.blast_trigger_ack_rejections' in conn.executed[0][0]

@pytest.mark.asyncio
async def test_stale_state_rejected_and_audited():
    conn=Conn(state=0)
    assert not await call(conn,trigger=1)
    assert len(conn.executed)==1
    assert conn.executed[0][1][4]=='COMMAND_STATE_MISMATCH'

@pytest.mark.asyncio
async def test_role_mismatch_rejected():
    conn=Conn(sender='rover')
    assert not await call(conn,'ROVER-B1-01','base')
    assert conn.executed[0][1][4]=='ROLE_MISMATCH'

@pytest.mark.asyncio
async def test_failed_insert_rolls_back():
    conn=Conn();conn.fail_insert=True
    with pytest.raises(RuntimeError,match='Simulated INSERT failure'):
        await call(conn)
    assert conn.rolled_back

@pytest.mark.asyncio
@pytest.mark.parametrize('device_type,role,device_id,updates', [
    ('gnss_base', 'base', 'BASE-01', True),
    ('gnss_rover', 'rover', 'ROVER-B1-01', False),
    ('gnss_rover', 'gnss_rover', 'ROVER-B1-02', False),
])
async def test_real_database_types_are_accepted(device_type, role, device_id, updates):
    conn = Conn(sender=device_type)
    assert await call(conn, device_id, role)
    assert len(conn.executed) == (2 if updates else 1)
    assert 'INSERT INTO public.blast_trigger_acks' in conn.executed[-1][0]
    assert conn.executed[-1][1][0] == device_id
