from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt
from common.errors import TokenExpiredError, TokenInvalidError
_hasher = PasswordHasher()
_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-insecure-secret-change-me")
_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MIN = 15
REFRESH_TOKEN_TTL_DAYS = 7
def hash_password(plain: str) -> str:
    return _hasher.hash(plain)
def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False
@dataclass(frozen=True)
class TokenPayload:
    sub: str
    role: str
    mfa_verified: bool
def _create_token(payload: TokenPayload, ttl: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": payload.sub,
        "role": payload.role,
        "mfa": payload.mfa_verified,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(claims, _SECRET_KEY, algorithm=_ALGORITHM)
def create_access_token(payload: TokenPayload) -> str:
    return _create_token(payload, timedelta(minutes=ACCESS_TOKEN_TTL_MIN), "access")
def create_refresh_token(payload: TokenPayload) -> str:
    return _create_token(payload, timedelta(days=REFRESH_TOKEN_TTL_DAYS), "refresh")
def decode_token(token: str, expected_type: str = "access") -> TokenPayload:
    try:
        claims = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except JWTError as exc:
        raise TokenInvalidError(str(exc)) from exc
    if claims.get("type") != expected_type:
        raise TokenInvalidError(f"expected a '{expected_type}' token")
    return TokenPayload(sub=claims["sub"], role=claims["role"], mfa_verified=bool(claims.get("mfa", False)))
ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}
def role_satisfies(actual_role: str, required_role: str) -> bool:
    return ROLE_RANK.get(actual_role, -1) >= ROLE_RANK.get(required_role, 99)
