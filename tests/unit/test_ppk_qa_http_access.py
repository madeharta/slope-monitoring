"""B13.5-B: real JWT + HTTP route acceptance; no DB/network writes."""
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.middlewares.error_handler import register_error_handlers
from apps.api.routers.v1.ppk import router
from common.security import TokenPayload, create_access_token
from unittest.mock import AsyncMock
from apps.api.routers.v1 import ppk as ppk_module


class _FakeConn:
    async def fetch(self, query, *args):
        assert "public.ppk_qa_experimental_solutions" in query
        return []


class _FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield _FakeConn()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('PPK_QA_SITE_ACCESS_JSON', '{"ITB-STAGING-01":["1001"]}')
    # Only account DB lookup is stubbed; real HTTP Bearer/JWT/RBAC still run.
    monkeypatch.setattr(ppk_module, 'require_active_ppk_qa_user', AsyncMock())
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    app.state.ppk_qa_db_pool = _FakePool()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.mark.parametrize("path", ["/api/v1/ppk/qa/rovers", "/api/v1/ppk/qa/solutions"])
def test_qa_requires_login(client, path):
    response = client.get(path, params={"site_id": "ITB-STAGING-01"})
    assert response.status_code == 401, response.text


@pytest.mark.parametrize("path", ["/api/v1/ppk/qa/rovers", "/api/v1/ppk/qa/solutions"])
@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_registered_roles_can_read_qa(client, path, role):
    token = create_access_token(TokenPayload(sub="1001", role=role, mfa_verified=False))
    response = client.get(path, params={"site_id": "ITB-STAGING-01"}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, (role, path, response.text)
    obj = response.json()
    assert obj["availability_status"] == "available"
    if path.endswith("/solutions"):
        assert obj["operational_displacement_approved"] is False
        assert obj["validation_status"] == "unvalidated"
        assert obj["rows"] == []
    else:
        assert obj["rovers"] == []


@pytest.mark.parametrize("path", ["/api/v1/ppk/qa/rovers", "/api/v1/ppk/qa/solutions"])
def test_invalid_jwt_denied(client, path):
    response = client.get(path, headers={"Authorization": "Bearer invalid.jwt.token"})
    assert response.status_code == 401 or response.status_code == 403, response.text


@pytest.mark.parametrize("path", ["/api/v1/ppk/qa/rovers", "/api/v1/ppk/qa/solutions"])
def test_qa_site_denied_with_valid_jwt(client, monkeypatch, path):
    monkeypatch.delenv('PPK_QA_SITE_ACCESS_JSON', raising=False)
    token = create_access_token(TokenPayload(sub="1001", role="viewer", mfa_verified=False))
    response = client.get(path, params={"site_id": "ITB-STAGING-01"},
                          headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403, response.text
