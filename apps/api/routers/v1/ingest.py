from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Request, Response

from apps.api.dependencies import get_canonicalization_service, get_db_pool
from common.errors import ConflictError, InvalidCsvError
from services.device_config_service.config_repository import DeviceConfigRepository
from services.ingestion_service.csv_validator import (
    retained_upload_headers,
    validate_headers,
    validate_path_file_name,
    validate_record_count,
)
from services.ingestion_service.file_upload_repository import (
    FileUploadRepository,
    UploadPayloadMismatchError,
)
from services.ingestion_service.protocol_router import route_and_parse
from services.ingestion_service.raw_staging_repository import RawStagingRepository

router = APIRouter(prefix="/api/upload", tags=["ingest"])


@router.post("/{file_name}")
async def upload_data(file_name: str, request: Request) -> Response:
    raw_body = await request.body()
    try:
        raw_csv = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCsvError("CSV body must be valid UTF-8") from exc

    headers = validate_headers(request.headers)
    validate_path_file_name(file_name, headers)
    validate_record_count(raw_csv, headers.record_count)
    parsed = route_and_parse(headers, raw_csv)
    pool = get_db_pool(request)
    config = await DeviceConfigRepository(pool).get_contract_config(headers.device_id)
    file_uploads = FileUploadRepository(pool)
    claim = await file_uploads.claim_for_processing(
        file_name=headers.file_name,
        device_id=headers.device_id,
        data_type=headers.data_type,
        communication_mode=headers.communication_mode,
        upload_origin=headers.upload_origin,
        record_count=headers.record_count,
    )
    if claim.action == "duplicate":
        try:
            await file_uploads.assert_retained_payload_matches(
                file_name=headers.file_name,
                payload=raw_body,
            )
        except UploadPayloadMismatchError as exc:
            raise ConflictError(str(exc)) from exc
        return Response(
            status_code=200,
            content=json.dumps({"ok": True, "duplicate": True, "config": config}),
            media_type="application/json",
        )
    if claim.action == "in_progress":
        raise ConflictError(f"upload '{headers.file_name}' is already being processed; retry later")
    try:
        await file_uploads.retain_original_payload(
            file_name=headers.file_name,
            payload=raw_body,
            content_type=request.headers.get("content-type", "text/csv"),
            request_headers=retained_upload_headers(request.headers),
        )
        async with pool.acquire() as conn:
            await conn.execute("UPDATE devices SET last_seen = now() WHERE device_id = $1", headers.device_id)
        canon = get_canonicalization_service(request)
        if parsed.rawx_rows:
            await canon.handle_gnss_rows(
                device_id=headers.device_id,
                device_role=headers.device_role,
                file_name=headers.file_name,
                rows=parsed.rawx_rows,
            )
        if parsed.position_rows:
            by_device: dict[str, list] = defaultdict(list)
            for row in parsed.position_rows:
                by_device[row.device_id].append(row)
            for rover_device_id, rows in by_device.items():
                await canon.handle_position_rows(
                    device_id=rover_device_id,
                    rows=rows,
                    file_name=headers.file_name,
                )
        if parsed.accel_rows:
            await canon.handle_accel_rows(
                device_id=headers.device_id,
                rows=parsed.accel_rows,
                file_name=headers.file_name,
                communication_mode=headers.communication_mode,
            )
        if parsed.blast_rawx_rows:
            await RawStagingRepository(pool).insert_gnss_raw_batch([
                (device_id, ts, raw, headers.file_name) for device_id, ts, raw in parsed.blast_rawx_rows
            ])
        await file_uploads.mark_processed(headers.file_name)
        return Response(
            status_code=200,
            content=json.dumps({"ok": True, "config": config}),
            media_type="application/json",
        )
    except UploadPayloadMismatchError as exc:
        await file_uploads.mark_failed(headers.file_name, f"{type(exc).__name__}: {exc}")
        raise ConflictError(str(exc)) from exc
    except Exception as exc:
        await file_uploads.mark_failed(headers.file_name, f"{type(exc).__name__}: {exc}")
        raise
