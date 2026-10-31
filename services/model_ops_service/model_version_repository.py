"""Persists model lifecycle events to the `model_versions` DB table
(migration 004) — closes a gap found 2026-09-19 while adding audit_log
integrity validation (migration 008): the in-memory `ModelRegistry`
(ml/registry/model_registry.py) tracked versions ONLY in-process, never
writing to this table. That table existed since the start but sat empty.
This repository is what actually populates it, called alongside (not
instead of) the in-memory registry from apps/api/routers/v1/model_ops.py.
"""

from __future__ import annotations

from datetime import datetime, timezone


class ModelVersionRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def upsert_registered(self, model_type: str, version_id: str, artifact_path: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO model_versions (version_id, model_type, artifact_path, status)
                VALUES ($1, $2, $3, 'registered')
                ON CONFLICT (version_id) DO UPDATE SET
                    model_type = EXCLUDED.model_type, artifact_path = EXCLUDED.artifact_path
                """,
                version_id, model_type, artifact_path,
            )

    async def mark_active(self, version_id: str) -> None:
        """Also demotes any OTHER row currently marked 'active' back to
        'retired' — at most one version should read as active in the DB,
        mirroring the in-memory registry's single-active-model invariant."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE model_versions SET status = 'retired' WHERE status = 'active' AND version_id != $1",
                    version_id,
                )
                await conn.execute(
                    "UPDATE model_versions SET status = 'active', activated_at = $2 WHERE version_id = $1",
                    version_id, datetime.now(timezone.utc),
                )
