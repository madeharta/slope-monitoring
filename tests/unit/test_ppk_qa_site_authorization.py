"""B13 release: PPK QA site authorization and JWT regression."""

import pytest
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.middlewares.error_handler import register_error_handlers
from apps.api.routers.v1.ppk import router
from common.security import TokenPayload, create_access_token


SITE = "ITB-STAGING-01"
PATHS = (
    "/api/v1/ppk/qa/rovers",
    "/api/v1/ppk/qa/solutions",
)


class FakeConn:
    async def fetch(self, query, *args):
        assert "public.ppk_qa_experimental_solutions" in query
        assert args[0] == SITE
        return []


class FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield FakeConn()


def auth_headers(role="viewer", user_id="1001"):
    token = create_access_token(
        TokenPayload(
            sub=user_id,
            role=role,
            mfa_verified=False,
        )
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(
        "PPK_QA_SITE_ACCESS_JSON",
        '{"ITB-STAGING-01":["1001","1002","1003"]}',
    )

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    app.state.ppk_qa_db_pool = FakePool()

    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_authorized_roles_can_read_qa(client, path, role):
    response = client.get(
        path,
        params={"site_id": SITE},
        headers=auth_headers(role),
    )
    assert response.status_code == 200, response.text
    assert response.json()["availability_status"] == "available"


@pytest.mark.parametrize("path", PATHS)
def test_unauthorized_user_denied(client, path):
    response = client.get(
        path,
        params={"site_id": SITE},
        headers=auth_headers(user_id="9999"),
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path", PATHS)
def test_cross_site_access_denied(client, path):
    response = client.get(
        path,
        params={"site_id": "OTHER-SITE"},
        headers=auth_headers(),
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path", PATHS)
def test_missing_allowlist_fails_closed(client, monkeypatch, path):
    monkeypatch.delenv("PPK_QA_SITE_ACCESS_JSON", raising=False)

    response = client.get(
        path,
        params={"site_id": SITE},
        headers=auth_headers(),
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path", PATHS)
def test_malformed_allowlist_fails_closed(client, monkeypatch, path):
    monkeypatch.setenv("PPK_QA_SITE_ACCESS_JSON", "{invalid-json")

    response = client.get(
        path,
        params={"site_id": SITE},
        headers=auth_headers(),
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path", PATHS)
def test_missing_jwt_denied(client, path):
    response = client.get(path, params={"site_id": SITE})
    assert response.status_code == 401, response.text


@pytest.mark.parametrize("path", PATHS)
def test_invalid_jwt_denied(client, path):
    response = client.get(
        path,
        params={"site_id": SITE},
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )
    assert response.status_code in (401, 403), response.text


@pytest.mark.parametrize("path", PATHS)
def test_missing_qa_pool_returns_503(client, path):
    client.app.state.ppk_qa_db_pool = None

    response = client.get(
        path,
        params={"site_id": SITE},
        headers=auth_headers(),
    )
    assert response.status_code == 503, response.text
