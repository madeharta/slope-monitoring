from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.v1 import blast


HEADERS = {
    "X-Device-Id": "BASE-01",
    "X-Device-Role": "base",
    "X-ICCID": "-1",
    "X-Device-Version": "1.0.0",
}

BODY = {
    "device_id": "BASE-01",
    "trigger_start": 1,
    "received": True,
    "timestamp_utc": "2026-10-27 18:00:00",
}


def make_client():
    app = FastAPI()
    app.include_router(blast.router)
    return TestClient(app, raise_server_exceptions=False)


def test_trigger_ack_endpoint_exists():
    with make_client() as client:
        response = client.post(
            "/api/v1/blast/trigger-ack",
            headers=HEADERS,
            json=BODY,
        )
    assert response.status_code != 404


def test_trigger_ack_rejects_device_mismatch():
    body = {**BODY, "device_id": "ROVER-OTHER"}

    with make_client() as client:
        response = client.post(
            "/api/v1/blast/trigger-ack",
            headers=HEADERS,
            json=body,
        )
    assert response.status_code in {400, 422}


def test_trigger_ack_rejects_invalid_state():
    body = {**BODY, "trigger_start": 2}

    with make_client() as client:
        response = client.post(
            "/api/v1/blast/trigger-ack",
            headers=HEADERS,
            json=body,
        )
    assert response.status_code in {400, 422}


def test_trigger_ack_rejects_received_false():
    body = {**BODY, "received": False}

    with make_client() as client:
        response = client.post(
            "/api/v1/blast/trigger-ack",
            headers=HEADERS,
            json=body,
        )
    assert response.status_code in {400, 422}


import pytest
from unittest.mock import AsyncMock


@pytest.mark.parametrize("trigger_start", [0, 1])
def test_trigger_ack_arm_disarm_http_200(monkeypatch, trigger_start):
    from apps.api.routers.v1 import blast

    ack = AsyncMock(return_value=True)

    monkeypatch.setattr(
        blast,
        "acknowledge_trigger_start",
        ack,
    )
    monkeypatch.setattr(
        blast,
        "get_db_pool",
        lambda request: object(),
    )

    body = {
        **BODY,
        "trigger_start": trigger_start,
    }

    with make_client() as client:
        response = client.post(
            "/api/v1/blast/trigger-ack",
            headers=HEADERS,
            json=body,
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    ack.assert_awaited_once()

    assert ack.await_args.kwargs["device_id"] == "BASE-01"
    assert ack.await_args.kwargs["trigger_start"] == trigger_start


def test_trigger_ack_stale_command_http_409(monkeypatch):
    ack = AsyncMock(return_value=False)

    monkeypatch.setattr(
        blast,
        "acknowledge_trigger_start",
        ack,
    )
    monkeypatch.setattr(
        blast,
        "get_db_pool",
        lambda request: object(),
    )

    with make_client() as client:
        response = client.post(
            "/api/v1/blast/trigger-ack",
            headers=HEADERS,
            json=BODY,
        )

    assert response.status_code == 409


def test_trigger_ack_empty_timestamp_accepted(monkeypatch):
    ack = AsyncMock(return_value=True)

    monkeypatch.setattr(blast, "acknowledge_trigger_start", ack)
    monkeypatch.setattr(
        blast, "get_db_pool", lambda request: object()
    )

    with make_client() as client:
        response = client.post(
            "/api/v1/blast/trigger-ack",
            headers=HEADERS,
            json={**BODY, "timestamp_utc": ""},
        )

    assert response.status_code == 200, response.text


def test_trigger_ack_missing_iccid_rejected(monkeypatch):
    headers = dict(HEADERS)
    headers.pop("X-ICCID")

    with make_client() as client:
        response = client.post(
            "/api/v1/blast/trigger-ack",
            headers=headers,
            json=BODY,
        )

    assert response.status_code == 422
