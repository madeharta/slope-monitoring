from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from apps.api.dependencies import get_db_pool, require_role
from common.audit import AuditLog
from common.errors import MissingHeaderError
from common.security import TokenPayload
from services.device_config_service.config_repository import ConfigWrite, DeviceConfigRepository
router = APIRouter(prefix="/api/v1/device", tags=["device_config"])
compat_router = APIRouter(tags=["device_config"])
async def _get_config(request: Request, x_device_id: str | None) -> dict:
    if not x_device_id:
        raise MissingHeaderError("X-Device-Id")
    config = await DeviceConfigRepository(get_db_pool(request)).get_contract_config(x_device_id)
    return {"ok": True, "config": config}
@router.get("/config")
async def get_device_config(request: Request, x_device_id: str | None = Header(default=None)) -> dict:
    return await _get_config(request, x_device_id)
@compat_router.get("/api/config")
async def get_device_config_compat(request: Request, x_device_id: str | None = Header(default=None)) -> dict:
    return await _get_config(request, x_device_id)
class ConfigPushRequest(BaseModel):
    config_key: str
    config_value: Any
@router.put("/config/{device_id}")
async def push_device_config(
    device_id: str,
    body: ConfigPushRequest,
    request: Request,
    user: TokenPayload = Depends(require_role("operator")),
) -> dict:
    pool = get_db_pool(request)
    await DeviceConfigRepository(pool).write_value(
        ConfigWrite(device_id=device_id, config_key=body.config_key, config_value=body.config_value, updated_by=user.sub)
    )
    await AuditLog(pool).record(
        actor_user_id=user.sub,
        action="device_config.update",
        target_type="device",
        target_id=device_id,
        new_value={body.config_key: body.config_value},
    )
    return {"ok": True}
