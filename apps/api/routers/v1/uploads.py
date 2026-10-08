from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response

from apps.api.dependencies import get_db_pool, require_role
from common.audit import AuditLog
from common.errors import NotFoundError
from common.security import TokenPayload
from services.ingestion_service.file_upload_repository import FileUploadRepository

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


def _iso(value):
    return value.isoformat() if value else None


@router.get("")
async def list_uploads(
    request: Request,
    user: TokenPayload = Depends(require_role("viewer")),
    site_id: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    data_type: str | None = Query(default=None),
    communication_mode: str | None = Query(default=None),
    processing_status: str | None = Query(default=None),
    file_name: str | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    pool = get_db_pool(request)
    total, rows = await FileUploadRepository(pool).list_uploads(
        site_id=site_id,
        device_id=device_id,
        data_type=data_type,
        communication_mode=communication_mode,
        processing_status=processing_status,
        file_name_query=file_name,
        from_time=from_time,
        to_time=to_time,
        limit=limit,
        offset=offset,
    )
    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "uploads": [
            {
                "file_name": row["file_name"],
                "device_id": row["device_id"],
                "site_id": row["site_id"],
                "data_type": row["data_type"],
                "communication_mode": row["communication_mode"],
                "upload_origin": row["upload_origin"],
                "record_count": row["record_count"],
                "received_at": _iso(row["received_at"]),
                "processing_status": row["processing_status"],
                "processing_attempts": row["processing_attempts"],
                "processing_started_at": _iso(row["processing_started_at"]),
                "processed_at": _iso(row["processed_at"]),
                "failed_at": _iso(row["failed_at"]),
                "last_error": row["last_error"],
                "original_available": bool(row["original_available"]),
                "sha256": row["sha256"],
                "byte_length": row["byte_length"],
                "content_type": row["content_type"],
                "stored_at": _iso(row["stored_at"]),
            }
            for row in rows
        ],
    }


@router.get("/{file_name}/download")
async def download_original_upload(
    file_name: str,
    request: Request,
    user: TokenPayload = Depends(require_role("operator")),
) -> Response:
    pool = get_db_pool(request)
    row = await FileUploadRepository(pool).get_original_payload(file_name)
    if row is None:
        raise NotFoundError("retained original upload", file_name)

    await AuditLog(pool).record(
        actor_user_id=user.sub,
        action="upload.download_original",
        target_type="file_upload",
        target_id=file_name,
        new_value={"sha256": row["sha256"], "byte_length": row["byte_length"]},
    )
    encoded_name = quote(file_name, safe="")
    return Response(
        content=bytes(row["payload"]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": row["sha256"],
            "X-Content-Bytes": str(row["byte_length"]),
        },
    )
