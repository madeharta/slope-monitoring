"""POST /api/v1/auth/login — sitemap Login & RBAC.

MFA (2026-09-19): POST /auth/mfa/enroll, POST /auth/mfa/verify — see
services/auth_service/mfa_service.py.

Silent token refresh (2026-09-20, item pending sejak awal — baru
dikerjakan sekarang): POST /auth/refresh. Access token 15 menit, refresh
token 7 hari, REFRESH TOKEN DI-ROTASI setiap dipakai (best practice —
membatasi jendela replay kalau refresh token lama bocor).

Audit logging (2026-09-20, sebelumnya TIDAK ADA sama sekali untuk login):
login sukses DAN gagal dicatat — riwayat login gagal sendiri adalah
sinyal keamanan (percobaan berulang ke satu email = indikasi brute-force).
"""

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
    """Tidak butuh audit log — ini bukan aksi baru dari sudut pandang
    keamanan, cuma memperpanjang sesi yang sudah diautentikasi lewat
    login (yang SUDAH tercatat). Mencatat setiap refresh (bisa terjadi
    puluhan kali per sesi) akan membanjiri audit_log tanpa nilai
    tambah — noise, bukan sinyal (prinsip yang sama dipakai untuk tidak
    mengaudit setiap request GET biasa)."""
    payload = decode_token(body.refresh_token, expected_type="refresh")
    return RefreshResponse(
        access_token=create_access_token(payload),
        refresh_token=create_refresh_token(payload),  # rotated
    )


@router.post("/mfa/enroll", response_model=MFAEnrollResponse)
async def mfa_enroll(request: Request, user: TokenPayload = Depends(get_current_user)) -> MFAEnrollResponse:
    """Any authenticated user can enroll — does NOT require mfa_verified
    (that would be circular: you can't verify MFA before enrolling it).
    Re-enrolling (calling this again) overwrites the previous secret and
    resets to unconfirmed — the old authenticator entry stops working
    immediately, by design (prevents a stale/lost-phone secret lingering)."""
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
    """Dual purpose, distinguished by the account's current mfa_enabled state:
      - mfa_enabled=False -> this IS the enrollment-confirmation call.
        Success flips mfa_enabled=True. No new token issued (the current
        session's mfa_verified claim is irrelevant to enrollment).
      - mfa_enabled=True  -> this is a LOGIN-time challenge. Success issues
        a NEW access token with mfa_verified=True."""
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
