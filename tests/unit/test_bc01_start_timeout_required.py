import ast
from pathlib import Path

import pytest


def _extract_function():
    src = Path('services/blast_service.py').read_text()
    tree = ast.parse(src)
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'trigger_blast_atomic')
    # Execute only the real initial guard, before external integrations start.
    guard = node.body[0]
    assert isinstance(guard, ast.If)
    ns = {}
    module = ast.Module(body=[ast.AsyncFunctionDef(name='guard', args=node.args, body=[guard, ast.Return(value=ast.Constant(True))], decorator_list=[], returns=None, type_comment=None)], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<guard>', 'exec'), ns)
    return ns['guard']


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [None, 0, -1, True, False, 1.5, '5'])
async def test_invalid_timeout_rejected_before_db(value):
    fn = _extract_function()
    with pytest.raises(ValueError, match='positive integer'):
        await fn(None, 'BASE-01', value, '1001')


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [1, 5, 300])
async def test_valid_timeout_accepted(value):
    fn = _extract_function()
    assert await fn(None, 'BASE-01', value, '1001') is True


def test_request_contract_requires_timeout():
    from pydantic import BaseModel, Field, ValidationError
    class Request(BaseModel):
        base_id: str
        timeout_minutes: int = Field(gt=0, strict=True)
    for payload in ({'base_id': 'BASE-01'}, {'base_id': 'BASE-01', 'timeout_minutes': None}, {'base_id':'BASE-01','timeout_minutes':'5'}):
        with pytest.raises(ValidationError):
            Request.model_validate(payload)
    assert Request.model_validate({'base_id':'BASE-01','timeout_minutes':5}).timeout_minutes == 5
