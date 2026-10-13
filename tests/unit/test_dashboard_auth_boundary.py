"""Dashboard auth boundary: no database connection required for rejected requests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from apps.api.middlewares.error_handler import register_error_handlers
from apps.api.routers.v1.dashboard import router
from common.security import TokenPayload, create_access_token

app = FastAPI()
register_error_handlers(app)
app.include_router(router)
client = TestClient(app)

@pytest.mark.parametrize("path", ["/api/overview", "/api/sites/site-01", "/api/stream"])
def test_dashboard_requires_bearer(path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"

@pytest.mark.parametrize("path", ["/api/overview", "/api/sites/site-01", "/api/stream"])
def test_dashboard_rejects_invalid_bearer(path):
    response = client.get(path, headers={"Authorization": "Bearer broken.jwt.value"})
    assert response.status_code == 401

@pytest.mark.parametrize("path", ["/api/overview", "/api/sites/site-01", "/api/stream"])
def test_dashboard_rejects_unknown_role(path):
    token = create_access_token(TokenPayload(sub="tester", role="invalid-role", mfa_verified=False))
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
