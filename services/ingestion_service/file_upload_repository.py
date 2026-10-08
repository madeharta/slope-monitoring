from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True)
class UploadClaim:
    action: str
    row: dict


class UploadPayloadMismatchError(RuntimeError):
    pass


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

    async def retain_original_payload(
        self,
        *,
        file_name: str,
        payload: bytes,
        content_type: str,
        request_headers: dict[str, str],
    ) -> dict:
        digest = hashlib.sha256(payload).hexdigest()
        byte_length = len(payload)
        async with self._pool.acquire() as conn:
            inserted = await conn.fetchrow(
                """
                INSERT INTO file_upload_payloads
                    (file_name, payload, sha256, byte_length, content_type, request_headers)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (file_name) DO NOTHING
                RETURNING sha256, byte_length, content_type, request_headers, stored_at
                """,
                file_name,
                payload,
                digest,
                byte_length,
                content_type,
                request_headers,
            )
            if inserted is not None:
                return dict(inserted)
            existing = await conn.fetchrow(
                """
                SELECT sha256, byte_length, content_type, request_headers, stored_at
                FROM file_upload_payloads
                WHERE file_name = $1
                """,
                file_name,
            )
        if existing is None:
            raise RuntimeError(f"retained upload payload row disappeared for {file_name!r}")
        if existing["sha256"] != digest or existing["byte_length"] != byte_length:
            raise UploadPayloadMismatchError(
                f"file_name {file_name!r} was already associated with different upload bytes"
            )
        return dict(existing)

    async def assert_retained_payload_matches(self, *, file_name: str, payload: bytes) -> bool | None:
        digest = hashlib.sha256(payload).hexdigest()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT sha256, byte_length FROM file_upload_payloads WHERE file_name = $1",
                file_name,
            )
        if row is None:
            return None
        if row["sha256"] != digest or row["byte_length"] != len(payload):
            raise UploadPayloadMismatchError(
                f"duplicate file_name {file_name!r} has different upload bytes"
            )
        return True

    async def get_original_payload(self, file_name: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT p.file_name, p.payload, p.sha256, p.byte_length, p.content_type,
                       p.request_headers, p.stored_at,
                       u.device_id, u.data_type, u.communication_mode, u.received_at,
                       u.processing_status
                FROM file_upload_payloads p
                JOIN file_uploads u ON u.file_name = p.file_name
                WHERE p.file_name = $1
                """,
                file_name,
            )
        return dict(row) if row else None

    async def list_uploads(
        self,
        *,
        site_id: str | None = None,
        device_id: str | None = None,
        data_type: str | None = None,
        communication_mode: str | None = None,
        processing_status: str | None = None,
        file_name_query: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[dict]]:
        where: list[str] = []
        args: list = []

        def add(value, clause: str) -> None:
            if value is not None and value != "":
                args.append(value)
                where.append(clause.format(n=len(args)))

        add(site_id, "d.site_id = ${n}")
        add(device_id, "u.device_id = ${n}")
        add(data_type, "u.data_type = ${n}")
        add(communication_mode, "u.communication_mode = ${n}")
        add(processing_status, "u.processing_status = ${n}")
        if file_name_query:
            args.append(f"%{file_name_query}%")
            where.append(f"u.file_name ILIKE ${len(args)}")
        add(from_time, "u.received_at >= ${n}")
        add(to_time, "u.received_at <= ${n}")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        async with self._pool.acquire() as conn:
            total = await conn.fetchval(
                f"""
                SELECT count(*)
                FROM file_uploads u
                LEFT JOIN devices d ON d.device_id = u.device_id
                {where_sql}
                """,
                *args,
            )
            rows = await conn.fetch(
                f"""
                SELECT u.file_name, u.device_id, d.site_id, u.data_type, u.communication_mode,
                       u.upload_origin, u.record_count, u.received_at,
                       u.processing_status, u.processing_attempts,
                       u.processing_started_at, u.processed_at, u.failed_at, u.last_error,
                       p.sha256, p.byte_length, p.content_type, p.stored_at,
                       (p.file_name IS NOT NULL) AS original_available
                FROM file_uploads u
                LEFT JOIN devices d ON d.device_id = u.device_id
                LEFT JOIN file_upload_payloads p ON p.file_name = u.file_name
                {where_sql}
                ORDER BY u.received_at DESC, u.file_name DESC
                LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}
                """,
                *args,
                limit,
                offset,
            )
        return int(total or 0), [dict(row) for row in rows]

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
