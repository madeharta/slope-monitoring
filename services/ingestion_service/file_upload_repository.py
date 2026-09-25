from __future__ import annotations
from dataclasses import dataclass
import asyncpg
@dataclass(frozen=True)
class UploadClaim:
    action: str
    row: dict
class FileUploadRepository:
    UniqueViolation = asyncpg.UniqueViolationError
    def __init__(self, pool) -> None:
        self._pool = pool
    async def get_by_file_name(self, file_name: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM file_uploads WHERE file_name = $1", file_name)
        return dict(row) if row else None
    async def claim_for_processing(
        self,
        *,
        file_name: str,
        device_id: str,
        data_type: str,
        communication_mode: str,
        upload_origin: str,
        record_count: int,
    ) -> UploadClaim:
        async with self._pool.acquire() as conn:
            inserted = await conn.fetchrow(
                """
                INSERT INTO file_uploads
                    (file_name, device_id, data_type, communication_mode, upload_origin, record_count,
                     processing_status, processing_attempts, processing_started_at,
                     processed_at, failed_at, last_error)
                VALUES ($1, $2, $3, $4, $5, $6,
                        'processing', 1, now(), NULL, NULL, NULL)
                ON CONFLICT (file_name) DO NOTHING
                RETURNING *
                """,
                file_name,
                device_id,
                data_type,
                communication_mode,
                upload_origin,
                record_count,
            )
            if inserted is not None:
                return UploadClaim("claimed", dict(inserted))
            retried = await conn.fetchrow(
                """
                UPDATE file_uploads
                SET processing_status = 'processing',
                    processing_attempts = processing_attempts + 1,
                    processing_started_at = now(),
                    processed_at = NULL,
                    failed_at = NULL,
                    last_error = NULL
                WHERE file_name = $1 AND processing_status = 'failed'
                RETURNING *
                """,
                file_name,
            )
            if retried is not None:
                return UploadClaim("claimed", dict(retried))
            row = await conn.fetchrow(
                "SELECT * FROM file_uploads WHERE file_name = $1",
                file_name,
            )
            if row is None:
                raise RuntimeError(f"upload ledger row disappeared for {file_name!r}")
            status = row["processing_status"]
            if status == "processed":
                return UploadClaim("duplicate", dict(row))
            return UploadClaim("in_progress", dict(row))
    async def mark_processed(self, file_name: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE file_uploads
                SET processing_status = 'processed',
                    processed_at = now(),
                    failed_at = NULL,
                    last_error = NULL
                WHERE file_name = $1
                """,
                file_name,
            )
    async def mark_failed(self, file_name: str, error_summary: str) -> None:
        safe_summary = (error_summary or "processing failed")[:2000]
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE file_uploads
                SET processing_status = 'failed',
                    failed_at = now(),
                    processed_at = NULL,
                    last_error = $2
                WHERE file_name = $1
                """,
                file_name,
                safe_summary,
            )
