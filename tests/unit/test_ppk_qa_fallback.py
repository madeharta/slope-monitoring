"""Integration-style endpoint contract tests with a simulated asyncpg pool."""
from common.security import TokenPayload
import asyncio
from unittest.mock import patch
import pytest
from apps.api.routers.v1 import ppk

class DBError(Exception):
    def __init__(self, state):
        self.sqlstate = state

class Connection:
    def __init__(self, result): self.result = result
    async def fetch(self, sql, *args):
        if isinstance(self.result, Exception): raise self.result
        return self.result

class Acquire:
    def __init__(self, result): self.result=result
    async def __aenter__(self): return Connection(self.result)
    async def __aexit__(self, *args): pass

class Pool:
    def __init__(self, result): self.result=result
    def acquire(self): return Acquire(self.result)

@pytest.mark.parametrize('endpoint', ['rovers','solutions'])
@pytest.mark.parametrize('result,status', [(DBError('42P01'),'schema_unavailable'),(DBError('42703'),'schema_unavailable'),([], 'available')])
def test_schema_state(endpoint, result, status):
    with patch.object(ppk, 'require_active_ppk_qa_user', new_callable=__import__('unittest.mock', fromlist=['AsyncMock']).AsyncMock), patch.object(ppk, 'get_ppk_qa_pool', return_value=Pool(result)):
        if endpoint=='rovers':
            body=asyncio.run(ppk.list_experimental_ppk_qa_rovers(request=None,user=TokenPayload(sub='1001', role='viewer', mfa_verified=False),site_id='ITB-STAGING-01'))
            assert body['rovers']==[]
        else:
            body=asyncio.run(ppk.list_experimental_ppk_qa_solutions(request=None,user=TokenPayload(sub='1001', role='viewer', mfa_verified=False),site_id='ITB-STAGING-01',rover_device_id='ROVER-B1-02',limit=500,time_range='all'))
            assert body['rows']==[]
            assert body['reference_type']=='PROVISIONAL_SPP'
            assert body['validation_status']=='unvalidated'
            assert body['operational_displacement_approved'] is False
        assert body['availability_status']==status

@pytest.mark.parametrize('endpoint', ['rovers','solutions'])
def test_other_sqlstate_propagates(endpoint):
    with patch.object(ppk, 'require_active_ppk_qa_user', new_callable=__import__('unittest.mock', fromlist=['AsyncMock']).AsyncMock), patch.object(ppk, 'get_ppk_qa_pool', return_value=Pool(DBError('42501'))):
        with pytest.raises(DBError):
            if endpoint=='rovers':
                asyncio.run(ppk.list_experimental_ppk_qa_rovers(request=None,user=TokenPayload(sub='1001', role='viewer', mfa_verified=False),site_id='ITB-STAGING-01'))
            else:
                asyncio.run(ppk.list_experimental_ppk_qa_solutions(request=None,user=TokenPayload(sub='1001', role='viewer', mfa_verified=False),site_id='ITB-STAGING-01',rover_device_id='ROVER-B1-02',limit=500,time_range='all'))
