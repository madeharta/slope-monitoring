"""B13: real active-account guard behavior with isolated fake pools."""
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.api.routers.v1.ppk import require_active_ppk_qa_user
from common.security import TokenPayload


class FakeConnection:
    def __init__(self, account=None, error=None):
        self.account = account
        self.error = error

    async def fetchrow(self, sql, user_id):
        assert "FROM public.users WHERE user_id=$1" in sql
        assert user_id == 1001
        if self.error:
            raise self.error
        return self.account


class FakePool:
    def __init__(self, account=None, error=None):
        self.connection = FakeConnection(account, error)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def request_with_pool(pool):
    return SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(db_pool=pool)
    ))


def token(role="viewer", sub="1001"):
    return TokenPayload(sub=sub, role=role, mfa_verified=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
async def test_active_account_allowed(role):
    account = {"disabled_at": None, "role": role}
    await require_active_ppk_qa_user(
        request_with_pool(FakePool(account)),
        token(role),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account",
    [
        None,
        {"disabled_at": "2026-10-24", "role": "viewer"},
        {"disabled_at": None, "role": "operator"},
    ],
)
async def test_disabled_missing_or_stale_role_denied(account):
    with pytest.raises(HTTPException) as error:
        await require_active_ppk_qa_user(
            request_with_pool(FakePool(account)),
            token(),
        )
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_operational_pool_returns_503():
    with pytest.raises(HTTPException) as error:
        await require_active_ppk_qa_user(
            request_with_pool(None),
            token(),
        )
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_invalid_subject_denied():
    with pytest.raises(HTTPException) as error:
        await require_active_ppk_qa_user(
            request_with_pool(FakePool()),
            token(sub="invalid"),
        )
    assert error.value.status_code == 403
