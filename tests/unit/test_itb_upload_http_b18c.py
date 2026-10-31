from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.v1 import ingest


CSV = (
    "device_id,timestamp_utc,latitude,longitude,"
    "altitude_m,rtk_status,h_acc_m,batt\n"
    "BASE-01,2026-10-27 00:00:00,"
    "-6.20000000,106.80000000,500.0000,2,0.0200,12.50\n"
    "ROVER-01,2026-10-27 00:00:00,"
    "-6.20010000,106.80010000,500.1000,2,0.0300,12.40\n"
)

FILE_NAME = "gnss_BASE-01_20261027_0000.csv"

HEADERS = {
    "X-Communication-Mode": "lora",
    "X-Device-Id": "BASE-01",
    "X-Device-Role": "base",
    "X-Data-Type": "gnss",
    "X-File-Name": FILE_NAME,
    "X-Record-Count": "2",
    "X-ICCID": "-1",
    "Content-Type": "text/csv",
}


def test_http_lora_upload_preserves_base_uploader(monkeypatch):
    class Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args):
            return "UPDATE 1"

    pool = Pool()

    repo = SimpleNamespace(
        claim_for_processing=AsyncMock(
            return_value=SimpleNamespace(action="process")
        ),
        retain_original_payload=AsyncMock(),
        mark_processed=AsyncMock(),
        mark_failed=AsyncMock(),
    )

    canon = SimpleNamespace(
        handle_position_rows=AsyncMock(),
    )

    monkeypatch.setattr(
        ingest, "get_db_pool", lambda request: pool
    )
    monkeypatch.setattr(
        ingest, "get_canonicalization_service",
        lambda request: canon
    )
    monkeypatch.setattr(
        ingest, "FileUploadRepository",
        lambda db_pool: repo
    )
    monkeypatch.setattr(
        ingest.DeviceConfigRepository,
        "get_contract_config",
        AsyncMock(return_value={}),
    )

    app = FastAPI()
    app.include_router(ingest.router)

    with TestClient(app) as client:
        response = client.post(
            f"/api/upload/{FILE_NAME}",
            headers=HEADERS,
            content=CSV.encode("utf-8"),
        )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True

    canon.handle_position_rows.assert_awaited_once()

    kwargs = canon.handle_position_rows.await_args.kwargs

    assert kwargs["device_id"] == "BASE-01"
    assert [
        sample.device_id for sample in kwargs["rows"]
    ] == ["BASE-01", "ROVER-01"]

    repo.retain_original_payload.assert_awaited_once()
    repo.mark_processed.assert_awaited_once()
    repo.mark_failed.assert_not_awaited()


def _http_test_app(monkeypatch, *, action="duplicate", match=True,
                   retain_error=None):
    from common.errors import ConflictError

    class Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args):
            return "UPDATE 1"

    repo = SimpleNamespace(
        claim_for_processing=AsyncMock(
            return_value=SimpleNamespace(action=action)
        ),
        assert_retained_payload_matches=AsyncMock(
            return_value=match
        ),
        retain_original_payload=AsyncMock(
            side_effect=retain_error
        ),
        mark_processed=AsyncMock(),
        mark_failed=AsyncMock(),
    )

    monkeypatch.setattr(
        ingest, "get_db_pool", lambda request: Pool()
    )
    monkeypatch.setattr(
        ingest.FileUploadRepository,
        "__new__",
        lambda cls, pool: repo,
    )
    monkeypatch.setattr(
        ingest.DeviceConfigRepository,
        "get_contract_config",
        AsyncMock(return_value={}),
    )

    app = FastAPI()

    @app.exception_handler(ConflictError)
    async def handle_conflict(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc)},
        )

    app.include_router(ingest.router)
    return app, repo


def test_http_missing_iccid_rejected(monkeypatch):
    app, repo = _http_test_app(monkeypatch)
    headers = dict(HEADERS)
    del headers["X-ICCID"]

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/upload/{FILE_NAME}",
            headers=headers,
            content=CSV.encode(),
        )

    assert response.status_code != 200
    repo.claim_for_processing.assert_not_awaited()


def test_http_identical_duplicate_acknowledged(monkeypatch):
    app, repo = _http_test_app(monkeypatch, match=True)

    with TestClient(app) as client:
        response = client.post(
            f"/api/upload/{FILE_NAME}",
            headers=HEADERS,
            content=CSV.encode(),
        )

    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    repo.retain_original_payload.assert_not_awaited()
    repo.mark_processed.assert_not_awaited()


def test_http_unverified_duplicate_rejected(monkeypatch):
    app, repo = _http_test_app(monkeypatch, match=None)

    with TestClient(app) as client:
        response = client.post(
            f"/api/upload/{FILE_NAME}",
            headers=HEADERS,
            content=CSV.encode(),
        )

    assert response.status_code == 409
    repo.mark_processed.assert_not_awaited()


def test_http_persistence_failure_not_acknowledged(monkeypatch):
    app, repo = _http_test_app(
        monkeypatch,
        action="process",
        retain_error=RuntimeError("simulated DB failure"),
    )

    with TestClient(
        app, raise_server_exceptions=False
    ) as client:
        response = client.post(
            f"/api/upload/{FILE_NAME}",
            headers=HEADERS,
            content=CSV.encode(),
        )

    assert response.status_code >= 500
    repo.mark_processed.assert_not_awaited()
    repo.mark_failed.assert_awaited_once()


def test_http_duplicate_different_payload_rejected(monkeypatch):
    from services.ingestion_service.file_upload_repository import (
        UploadPayloadMismatchError,
    )

    app, repo = _http_test_app(monkeypatch)

    repo.assert_retained_payload_matches.side_effect = (
        UploadPayloadMismatchError(
            "duplicate file has different upload bytes"
        )
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/upload/{FILE_NAME}",
            headers=HEADERS,
            content=CSV.encode(),
        )

    assert response.status_code == 409
    repo.mark_processed.assert_not_awaited()
    repo.retain_original_payload.assert_not_awaited()


def test_http_canonicalization_failure_marks_upload_failed(monkeypatch):
    app, repo = _http_test_app(
        monkeypatch,
        action="process",
    )

    canon = SimpleNamespace(
        handle_position_rows=AsyncMock(
            side_effect=RuntimeError(
                "simulated canonicalization failure"
            )
        ),
    )

    monkeypatch.setattr(
        ingest,
        "get_canonicalization_service",
        lambda request: canon,
    )

    with TestClient(
        app,
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/api/upload/{FILE_NAME}",
            headers=HEADERS,
            content=CSV.encode(),
        )

    assert response.status_code >= 500

    canon.handle_position_rows.assert_awaited_once()
    repo.retain_original_payload.assert_awaited_once()
    repo.mark_failed.assert_awaited_once()
    repo.mark_processed.assert_not_awaited()
