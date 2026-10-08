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
