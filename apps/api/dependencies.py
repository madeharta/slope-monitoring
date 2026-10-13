"""Dependency injection + RBAC guards. `require_role("operator")` is a
dependency FACTORY — call it inside a route's Depends(...), don't pass the
function itself, so the required role is bound per-route.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from common.errors import ForbiddenRoleError
from common.security import TokenPayload, decode_token, role_satisfies

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> TokenPayload:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(creds.credentials, expected_type="access")


def require_role(min_role: str):
    """Usage: `user: TokenPayload = Depends(require_role("operator"))`."""

    async def _dependency(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if not role_satisfies(user.role, min_role):
            raise ForbiddenRoleError(required_role=min_role, actual_role=user.role)
        return user

    return _dependency


def require_role_and_mfa(min_role: str):
    """For irreversible actions (blast trigger) — role AND a
    freshly-MFA-verified session, matching the sitemap's "konfirmasi
    2-langkah" requirement for /blast/trigger.

    Saklar mati eksplisit (2026-09-20, per permintaan pengguna): set
    `MFA_ENFORCEMENT_ENABLED=false` di .env untuk melewati pengecekan
    mfa_verified sepenuhnya selama fase testing — dinyalakan lagi untuk
    produksi. CATATAN JUJUR: sampai saat ini MFA TIDAK PERNAH benar-benar
    memblokir siapa pun secara tidak sengaja — `mfa_verified` otomatis
    True untuk akun yang belum pernah /mfa/enroll (mfa_enabled=False by
    default). Saklar ini murni kontrol eksplisit untuk jaga-jaga, bukan
    perbaikan atas bug yang sudah terjadi (error login 500 sebelumnya
    penyebabnya lain — lihat migrasi 010 dan PROJECT_AUDIT_LOG.md)."""
    import os

    async def _dependency(user: TokenPayload = Depends(require_role(min_role))) -> TokenPayload:
        if os.getenv("MFA_ENFORCEMENT_ENABLED", "true").lower() == "false":
            return user
        if not user.mfa_verified:
            raise ForbiddenRoleError(required_role=f"{min_role} (MFA-verified)", actual_role=user.role)
        return user

    return _dependency


def get_db_pool(request: Request):
    """asyncpg pool set on app.state during lifespan startup (see main.py).
    Exists so routers depend on this function, not on `request.app.state`
    directly — keeps router signatures testable with a fake pool."""
    return request.app.state.db_pool


def get_model_registry(request: Request):
    return request.app.state.model_registry


def get_canonicalization_service(request: Request):
    """Constructed once per request (cheap — just wraps repositories over
    the shared pool); the expensive part (RTKLibPPKEngine) is created lazily
    per-site inside CanonicalizationService via the factory on app.state,
    since each site has a different surveyed base reference (see
    ml/pipeline/preprocessing/ppk_engine.py)."""
    from services.monitoring_service.canonicalization_service import CanonicalizationService

    return CanonicalizationService(request.app.state.db_pool, request.app.state.ppk_engine_factory)
