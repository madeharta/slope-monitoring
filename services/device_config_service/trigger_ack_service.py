"""ITB TriggerStart acknowledgment persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _json_integer(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if type(value) is int else None


async def acknowledge_trigger_start(
    pool,
    *,
    device_id: str,
    trigger_start: int,
    device_role: str = "",
    iccid: str = "",
    device_version: str = "",
    device_timestamp_utc: datetime | None = None,
) -> bool:
    """Persist an ACK and update its matching pending configuration atomically.

    Returns False for stale or unmatched ACKs.
    Each accepted retry produces its own audit-history row.
    """
    if type(trigger_start) is not int or trigger_start not in (0, 1):
        return False

    async with pool.acquire() as conn:
        async with conn.transaction():
            active = await conn.fetchrow(
                """
                SELECT config_value
                FROM device_config
                WHERE device_id = $1
                  AND config_key = 'TriggerStart'
                FOR UPDATE
                """,
                device_id,
            )

            if active is None or _json_integer(active["config_value"]) != trigger_start:
                return False

            latest = await conn.fetchrow(
                """
                SELECT id, config_value, acked_at
                FROM device_config_pending
                WHERE device_id = $1
                  AND config_key = 'TriggerStart'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                FOR UPDATE
                """,
                device_id,
            )

            if latest is None or _json_integer(latest["config_value"]) != trigger_start:
                return False

            now = datetime.now(timezone.utc)

            if latest["acked_at"] is None:
                await conn.execute(
                    """
                    UPDATE device_config_pending
                    SET acked_at = $2
                    WHERE id = $1 AND acked_at IS NULL
                    """,
                    latest["id"],
                    now,
                )

            await conn.execute(
                """
                INSERT INTO blast_trigger_acks
                    (device_id, pending_config_id, trigger_start,
                     received, device_timestamp_utc, server_received_at,
                     device_role, iccid, device_version)
                VALUES ($1, $2, $3, TRUE, $4, $5, $6, $7, $8)
                """,
                device_id,
                latest["id"],
                trigger_start,
                device_timestamp_utc,
                now,
                device_role,
                iccid,
                device_version,
            )

            return True
