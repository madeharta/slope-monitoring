from __future__ import annotations
from dataclasses import dataclass
from common.errors import AppError, ErrorCode, InvalidCredentialsError, NotFoundError
from common.security import TokenPayload, create_access_token, create_refresh_token, hash_password, verify_password
@dataclass(frozen=True)
class LoginResult:
    access_token: str
    refresh_token: str
    role: str
class UserRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def get_by_email(self, email: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, email, password_hash, role, mfa_enabled, mfa_secret, disabled_at "
                "FROM users WHERE email = $1", email,
            )
        return dict(row) if row else None
    async def get_by_id(self, user_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, email, role, mfa_enabled, mfa_secret, disabled_at, created_at "
                "FROM users WHERE user_id = $1", int(user_id),
            )
        return dict(row) if row else None
    async def list_all(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, email, role, mfa_enabled, disabled_at, created_at FROM users ORDER BY email",
            )
        return [dict(r) for r in rows]
    async def create(self, email: str, password: str, role: str) -> int:
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "INSERT INTO users (email, password_hash, role) VALUES ($1, $2, $3) RETURNING user_id",
                    email, hash_password(password), role,
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolationError":
                    raise AppError(ErrorCode.VALIDATION_ERROR, f"email '{email}' sudah terdaftar") from exc
                raise
        return row["user_id"]
    async def update_role(self, user_id: str, role: str) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute("UPDATE users SET role = $2 WHERE user_id = $1", int(user_id), role)
        if result == "UPDATE 0":
            raise NotFoundError("user", user_id)
    async def count_active_admins(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM users WHERE role = 'admin' AND disabled_at IS NULL",
            )
    async def disable(self, user_id: str) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET disabled_at = now() WHERE user_id = $1 AND disabled_at IS NULL", int(user_id),
            )
        if result == "UPDATE 0":
            raise NotFoundError("user", user_id)
    async def enable(self, user_id: str) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute("UPDATE users SET disabled_at = NULL WHERE user_id = $1", int(user_id))
        if result == "UPDATE 0":
            raise NotFoundError("user", user_id)
    async def set_mfa_secret(self, user_id: str, secret: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE users SET mfa_secret = $1 WHERE user_id = $2", secret, int(user_id))
    async def confirm_mfa_enabled(self, user_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE users SET mfa_enabled = TRUE WHERE user_id = $1", int(user_id))
async def login(email: str, password: str, users: UserRepository, audit: "AuditLog | None" = None) -> LoginResult:
    user = await users.get_by_email(email)
    if user is None or not verify_password(password, user["password_hash"]):
        if audit is not None:
            await audit.record(actor_user_id=None, action="login.failure", target_type="user", target_id=email)
        raise InvalidCredentialsError()
    if user["disabled_at"] is not None:
        if audit is not None:
            await audit.record(actor_user_id=user["user_id"], action="login.failure_disabled", target_type="user", target_id=email)
        raise InvalidCredentialsError()
    payload = TokenPayload(sub=str(user["user_id"]), role=user["role"], mfa_verified=not user["mfa_enabled"])
    if audit is not None:
        await audit.record(actor_user_id=user["user_id"], action="login.success", target_type="user", target_id=email)
    return LoginResult(
        access_token=create_access_token(payload),
        refresh_token=create_refresh_token(payload),
        role=user["role"],
    )
