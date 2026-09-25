from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from apps.api.dependencies import get_db_pool, require_role_and_mfa
from common.audit import AuditLog
from common.security import TokenPayload
from services.device_config_service.config_repository import DeviceConfigRepository
router = APIRouter(prefix="/api/v1/blast", tags=["blast"])
class TriggerRequest(BaseModel):
    base_id: str
    timeout_minutes: int | None = Field(default=None, gt=0)
class ResetRequest(BaseModel):
    base_id: str
@router.post("/trigger")
async def trigger_blast(
    body: TriggerRequest,
    request: Request,
    user: TokenPayload = Depends(require_role_and_mfa("operator")),
) -> dict:
    pool = get_db_pool(request)
    await DeviceConfigRepository(pool).set_site_trigger(body.base_id, 1, body.timeout_minutes, user.sub)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO blast_trigger_commands (base_id, trigger_source, requested_by, status, executed_at)
            VALUES ($1, 'web_dashboard', $2, 'executed', now())
            RETURNING command_id
            """,
            body.base_id, user.sub,
        )
    await AuditLog(pool).record(
        actor_user_id=user.sub,
        action="blast.trigger",
        target_type="device",
        target_id=body.base_id,
        new_value={"TriggerStart": 1, "TimeOutTrigger": body.timeout_minutes},
    )
    return {"ok": True, "command_id": row["command_id"], "TriggerStart": 1, "delivery": "config"}
@router.post("/reset")
async def reset_blast_trigger(
    body: ResetRequest,
    request: Request,
    user: TokenPayload = Depends(require_role_and_mfa("operator")),
) -> dict:
    pool = get_db_pool(request)
    await DeviceConfigRepository(pool).set_site_trigger(body.base_id, 0, None, user.sub)
    await AuditLog(pool).record(
        actor_user_id=user.sub,
        action="blast.trigger_reset",
        target_type="device",
        target_id=body.base_id,
        new_value={"TriggerStart": 0},
    )
    return {"ok": True, "TriggerStart": 0}
