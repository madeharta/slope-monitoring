from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from apps.api.dependencies import get_db_pool, require_role
from common.audit import AuditLog
from common.errors import AppError, ErrorCode
from common.security import TokenPayload
from services.auth_service.user_service import UserRepository
router = APIRouter(prefix="/api/v1/users", tags=["users"])
_VALID_ROLES = ("viewer", "operator", "admin")
@router.get("")
async def list_users(request: Request, user: TokenPayload = Depends(require_role("admin"))) -> dict:
    pool = get_db_pool(request)
    users = await UserRepository(pool).list_all()
    return {
        "ok": True,
        "users": [
            {
                "user_id": u["user_id"], "email": u["email"], "role": u["role"],
                "mfa_enabled": u["mfa_enabled"],
                "disabled_at": u["disabled_at"].isoformat() if u["disabled_at"] else None,
                "created_at": u["created_at"].isoformat() if u["created_at"] else None,
            }
            for u in users
        ],
    }
class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str
@router.post("")
async def create_user(
    body: CreateUserRequest, request: Request, actor: TokenPayload = Depends(require_role("admin")),
) -> dict:
    if body.role not in _VALID_ROLES:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"role harus salah satu dari: {', '.join(_VALID_ROLES)}")
    if len(body.password) < 8:
        raise AppError(ErrorCode.VALIDATION_ERROR, "password minimal 8 karakter")
    pool = get_db_pool(request)
    new_user_id = await UserRepository(pool).create(body.email, body.password, body.role)
    await AuditLog(pool).record(
        actor_user_id=actor.sub, action="user.create", target_type="user", target_id=body.email,
        new_value={"role": body.role},
    )
    return {"ok": True, "user_id": new_user_id}
class UpdateUserRoleRequest(BaseModel):
    role: str
@router.put("/{user_id}/role")
async def update_user_role(
    user_id: str, body: UpdateUserRoleRequest, request: Request, actor: TokenPayload = Depends(require_role("admin")),
) -> dict:
    if body.role not in _VALID_ROLES:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"role harus salah satu dari: {', '.join(_VALID_ROLES)}")
    pool = get_db_pool(request)
    repo = UserRepository(pool)
    if user_id == actor.sub and body.role != "admin":
        current = await repo.get_by_id(user_id)
        if current and current["role"] == "admin":
            active_admins = await repo.count_active_admins()
            if active_admins <= 1:
                raise AppError(ErrorCode.VALIDATION_ERROR, "tidak bisa menurunkan role admin terakhir yang aktif — daftarkan admin lain dulu")
    await repo.update_role(user_id, body.role)
    await AuditLog(pool).record(
        actor_user_id=actor.sub, action="user.update_role", target_type="user", target_id=user_id,
        new_value={"role": body.role},
    )
    return {"ok": True}
@router.delete("/{user_id}")
async def disable_user(
    user_id: str, request: Request, actor: TokenPayload = Depends(require_role("admin")),
) -> dict:
    if user_id == actor.sub:
        raise AppError(ErrorCode.VALIDATION_ERROR, "tidak bisa menonaktifkan akun sendiri")
    pool = get_db_pool(request)
    repo = UserRepository(pool)
    target = await repo.get_by_id(user_id)
    if target and target["role"] == "admin":
        active_admins = await repo.count_active_admins()
        if active_admins <= 1:
            raise AppError(ErrorCode.VALIDATION_ERROR, "tidak bisa menonaktifkan admin terakhir yang aktif")
    await AuditLog(pool).record(actor_user_id=actor.sub, action="user.disable", target_type="user", target_id=user_id)
    await repo.disable(user_id)
    return {"ok": True}
@router.post("/{user_id}/enable")
async def enable_user(
    user_id: str, request: Request, actor: TokenPayload = Depends(require_role("admin")),
) -> dict:
    pool = get_db_pool(request)
    await UserRepository(pool).enable(user_id)
    await AuditLog(pool).record(actor_user_id=actor.sub, action="user.enable", target_type="user", target_id=user_id)
    return {"ok": True}
