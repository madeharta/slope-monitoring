from __future__ import annotations
from typing import Any
class AuditLog:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def record(
        self,
        actor_user_id: str | int | None,
        action: str,
        target_type: str,
        target_id: str,
        old_value: Any = None,
        new_value: Any = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (actor_user_id, action, target_type, target_id, old_value, new_value)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                int(actor_user_id) if actor_user_id is not None else None,
                action, target_type, target_id, old_value, new_value,
            )
