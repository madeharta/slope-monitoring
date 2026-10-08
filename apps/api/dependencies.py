from __future__ import annotations
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from common.errors import ForbiddenRoleError
from common.security import TokenPayload, decode_token, role_satisfies
_bearer = HTTPBearer(auto_error=True)
async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> TokenPayload:
    return decode_token(creds.credentials, expected_type="access")
def require_role(min_role: str):
    async def _dependency(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if not role_satisfies(user.role, min_role):
            raise ForbiddenRoleError(required_role=min_role, actual_role=user.role)
        return user
    return _dependency
def require_role_and_mfa(min_role: str):
    import os
    async def _dependency(user: TokenPayload = Depends(require_role(min_role))) -> TokenPayload:
        if os.getenv("MFA_ENFORCEMENT_ENABLED", "true").lower() == "false":
            return user
        if not user.mfa_verified:
            raise ForbiddenRoleError(required_role=f"{min_role} (MFA-verified)", actual_role=user.role)
        return user
    return _dependency
def get_db_pool(request: Request):
    return request.app.state.db_pool
def get_model_registry(request: Request):
    return request.app.state.model_registry
def get_canonicalization_service(request: Request):
    from services.monitoring_service.canonicalization_service import CanonicalizationService
    return CanonicalizationService(request.app.state.db_pool, request.app.state.ppk_engine_factory)
