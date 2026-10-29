from __future__ import annotations
from common.audit import AuditLog
from services.device_config_service.config_repository import DeviceConfigRepository

async def trigger_blast_atomic(
    pool,
    base_id: str,
    timeout_minutes: int,
    requested_by: str | int,
) -> int:
    if type(timeout_minutes) is not int or timeout_minutes <= 0:
        raise ValueError("timeout_minutes must be a positive integer")
    repo = DeviceConfigRepository(pool)
    audit = AuditLog(pool)
    # JWT sub is serialized as text, while blast_trigger_commands.requested_by is BIGINT.
    requested_by_id = int(requested_by)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Reuse this connection so an insert failure cannot leave partial config state.
            await repo.set_site_trigger_on_conn(
                conn, base_id, 1, timeout_minutes, str(requested_by)
            )
            row = await conn.fetchrow(
                """
                INSERT INTO blast_trigger_commands (base_id, trigger_source, requested_by, status, executed_at)
                VALUES ($1, 'web_dashboard', $2, 'executed', now())
                RETURNING command_id
                """,
                base_id, requested_by_id,
            )
            # Audit is part of the same transaction: audit failure rolls the trigger back.
            await audit.record_on_conn(
                conn,
                actor_user_id=requested_by_id,
                action="blast.trigger",
                target_type="device",
                target_id=base_id,
                new_value={"TriggerStart": 1, "TimeOutTrigger": timeout_minutes},
            )
    return int(row["command_id"])

async def reset_blast_atomic(
    pool,
    base_id: str,
    requested_by: str | int,
) -> None:
    repo = DeviceConfigRepository(pool)
    audit = AuditLog(pool)
    requested_by_id = int(requested_by)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # timeout_minutes=None means preserve the existing TimeOutTrigger value.
            await repo.set_site_trigger_on_conn(conn, base_id, 0, None, str(requested_by))
            await audit.record_on_conn(
                conn,
                actor_user_id=requested_by_id,
                action="blast.trigger_reset",
                target_type="device",
                target_id=base_id,
                new_value={"TriggerStart": 0},
            )
