from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from apps.api.dependencies import get_current_user, get_db_pool
from apps.api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MFAEnrollResponse,
    MFAVerifyRequest,
    MFAVerifyResponse,
    RefreshRequest,
    RefreshResponse,
)
from common.audit import AuditLog
from common.errors import AppError, ErrorCode, NotFoundError
from common.security import TokenPayload, create_access_token, create_refresh_token, decode_token
from services.auth_service.mfa_service import generate_secret, provisioning_uri, verify_code
from services.auth_service.user_service import UserRepository, login
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
@router.post("/login", response_model=LoginResponse)
async def login_endpoint(body: LoginRequest, request: Request) -> LoginResponse:
    pool = get_db_pool(request)
    users = UserRepository(pool)
    result = await login(body.email, body.password, users, audit=AuditLog(pool))
    return LoginResponse(access_token=result.access_token, refresh_token=result.refresh_token, role=result.role)
@router.post("/refresh", response_model=RefreshResponse)
async def refresh_endpoint(body: RefreshRequest) -> RefreshResponse:
    payload = decode_token(body.refresh_token, expected_type="refresh")
    return RefreshResponse(
        access_token=create_access_token(payload),
        refresh_token=create_refresh_token(payload),
    )
@router.post("/mfa/enroll", response_model=MFAEnrollResponse)
async def mfa_enroll(request: Request, user: TokenPayload = Depends(get_current_user)) -> MFAEnrollResponse:
    pool = get_db_pool(request)
    users = UserRepository(pool)
    account = await users.get_by_id(user.sub)
    if account is None:
        raise NotFoundError("user", user.sub)
    secret = generate_secret()
    await users.set_mfa_secret(user.sub, secret)
    await AuditLog(pool).record(actor_user_id=user.sub, action="mfa.enroll", target_type="user", target_id=account["email"])
    uri = provisioning_uri(secret, account["email"])
    return MFAEnrollResponse(secret=secret, provisioning_uri=uri)
@router.post("/mfa/verify", response_model=MFAVerifyResponse)
async def mfa_verify(
    body: MFAVerifyRequest, request: Request, user: TokenPayload = Depends(get_current_user),
) -> MFAVerifyResponse:
    pool = get_db_pool(request)
    users = UserRepository(pool)
    account = await users.get_by_id(user.sub)
    if account is None:
        raise NotFoundError("user", user.sub)
    if not account["mfa_secret"]:
        raise AppError(ErrorCode.VALIDATION_ERROR, "no MFA secret enrolled yet — call /auth/mfa/enroll first")
    if not verify_code(account["mfa_secret"], body.code):
        await AuditLog(pool).record(actor_user_id=user.sub, action="mfa.verify.failure", target_type="user", target_id=account["email"])
        raise AppError(ErrorCode.INVALID_CREDENTIALS, "invalid or expired MFA code")
    if not account["mfa_enabled"]:
        await users.confirm_mfa_enabled(user.sub)
        await AuditLog(pool).record(actor_user_id=user.sub, action="mfa.enroll.confirmed", target_type="user", target_id=account["email"])
        return MFAVerifyResponse(ok=True, mfa_enabled=True, access_token=None)
    await AuditLog(pool).record(actor_user_id=user.sub, action="mfa.verify.success", target_type="user", target_id=account["email"])
    upgraded = TokenPayload(sub=user.sub, role=user.role, mfa_verified=True)
    return MFAVerifyResponse(ok=True, mfa_enabled=True, access_token=create_access_token(upgraded))
