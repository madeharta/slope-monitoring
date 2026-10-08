from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from apps.api.dependencies import get_db_pool, require_role_and_mfa
from common.security import TokenPayload
from services.blast_service import reset_blast_atomic, trigger_blast_atomic
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
    command_id = await trigger_blast_atomic(
        pool, body.base_id, body.timeout_minutes, user.sub
    )
    return {"ok": True, "command_id": command_id, "TriggerStart": 1, "delivery": "config"}
@router.post("/reset")
async def reset_blast_trigger(
    body: ResetRequest,
    request: Request,
    user: TokenPayload = Depends(require_role_and_mfa("operator")),
) -> dict:
    pool = get_db_pool(request)
    await reset_blast_atomic(pool, body.base_id, user.sub)
    return {"ok": True, "TriggerStart": 0}
