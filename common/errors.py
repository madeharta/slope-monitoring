"""Centralized error handling (fills the gap flagged during blueprint review).

Design principles:
1. Every raised error maps to exactly one `ErrorCode`, which in turn maps to
   exactly one HTTP status — no ad-hoc `HTTPException(400, "...")` scattered
   across routers.
2. The response body shape is FIXED across the whole API:
       {"ok": false, "error": "<ErrorCode>", "detail": "<human message>"}
   This intentionally mirrors the `{"ok": false, "error": "..."}` shape
   already used in API Spec LoRa v1.3 / 4G v1.6, so device firmware parsing
   the response does not need two different error formats.
3. Device-facing errors (ingestion, device-config) reuse the SAME error codes
   the hardware team already implements against (INVALID_DEVICE_ID,
   MISSING_HEADER, INVALID_CSV, INVALID_BASE64). Dashboard/auth errors add
   new codes that only the frontend consumes — devices never see them.
4. Nothing here raises `HTTPException` directly. Routers/services raise
   `AppError` subclasses; a single FastAPI exception handler (see
   apps/api/middlewares/error_handler.py) converts them to responses. This
   keeps `services/` and `ml/` free of any FastAPI import.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    # --- Device-facing (contract with API Spec LoRa v1.3 / 4G v1.6 §9-11) ---
    INVALID_DEVICE_ID = "INVALID_DEVICE_ID"
    MISSING_HEADER = "MISSING_HEADER"
    INVALID_CSV = "INVALID_CSV"
    INVALID_BASE64 = "INVALID_BASE64"

    # --- Dashboard/auth-facing (new — not part of the device contract) ---
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    UNAUTHENTICATED = "UNAUTHENTICATED"  # no Authorization header at all — distinct from an invalid/expired one
    FORBIDDEN_ROLE = "FORBIDDEN_ROLE"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MODEL_INCOMPATIBLE = "MODEL_INCOMPATIBLE"  # §8.2 compatibility_check failure
    INTERNAL_ERROR = "INTERNAL_ERROR"


# HTTP status per code — single source of truth, referenced by the exception
# handler AND by tests/unit/test_errors.py so the mapping cannot silently drift.
STATUS_FOR: dict[ErrorCode, int] = {
    ErrorCode.INVALID_DEVICE_ID: 403,
    ErrorCode.MISSING_HEADER: 400,
    ErrorCode.INVALID_CSV: 400,
    ErrorCode.INVALID_BASE64: 400,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.TOKEN_INVALID: 401,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN_ROLE: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.MODEL_INCOMPATIBLE: 422,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    """Base of every application-raised error. Never raise this directly —
    raise a subclass, or construct one with an explicit `code=`."""

    def __init__(self, code: ErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        self.status_code = STATUS_FOR[code]
        super().__init__(f"{code.value}: {detail}")

    def to_envelope(self) -> dict:
        return {"ok": False, "error": self.code.value, "detail": self.detail}


# --- Device-facing convenience subclasses (§ Ingest, csv_validator.py) -----

class InvalidDeviceIdError(AppError):
    def __init__(self, device_id: str) -> None:
        super().__init__(ErrorCode.INVALID_DEVICE_ID, f"device_id '{device_id}' is not registered")


class MissingHeaderError(AppError):
    def __init__(self, header_name: str) -> None:
        super().__init__(ErrorCode.MISSING_HEADER, f"required header '{header_name}' is missing")


class InvalidCsvError(AppError):
    def __init__(self, reason: str) -> None:
        super().__init__(ErrorCode.INVALID_CSV, reason)


class InvalidBase64Error(AppError):
    def __init__(self, reason: str) -> None:
        super().__init__(ErrorCode.INVALID_BASE64, reason)


# --- Dashboard/auth-facing convenience subclasses --------------------------

class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.INVALID_CREDENTIALS, "email or password is incorrect")


class TokenExpiredError(AppError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.TOKEN_EXPIRED, "session token has expired, please log in again")


class TokenInvalidError(AppError):
    def __init__(self, reason: str = "token could not be verified") -> None:
        super().__init__(ErrorCode.TOKEN_INVALID, reason)


class ForbiddenRoleError(AppError):
    def __init__(self, required_role: str, actual_role: str) -> None:
        super().__init__(
            ErrorCode.FORBIDDEN_ROLE,
            f"this action requires role '{required_role}' or higher; you have '{actual_role}'",
        )


class NotFoundError(AppError):
    def __init__(self, entity: str, identifier: str) -> None:
        super().__init__(ErrorCode.NOT_FOUND, f"{entity} '{identifier}' not found")


class ConflictError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(ErrorCode.CONFLICT, detail)


class ModelIncompatibleError(AppError):
    """Raised by ModelRegistry.compatibility_check (§8.2) — MUST be raised
    and caught BEFORE any weight swap happens; the active model must never
    change as a side effect of a failed compatibility check."""

    def __init__(self, model_type: str, version_id: str, reason: str) -> None:
        super().__init__(
            ErrorCode.MODEL_INCOMPATIBLE,
            f"model '{model_type}:{version_id}' failed compatibility check: {reason}",
        )


class ModelTypeUnavailableError(AppError):
    """Wraps ml.registry.model_factory.ModelNotImplementedError /
    UnknownModelTypeError as an AppError (2026-09-18 fix — see
    PROJECT_AUDIT_LOG.md: a global `@app.exception_handler(ModelNotImplementedError)`
    was registered but never actually dispatched by Starlette for reasons
    not fully diagnosed without a live FastAPI environment to test against.
    Converting at the raise site to an AppError sidesteps the issue
    entirely by reusing the AppError dispatch path, which is proven
    working across every other endpoint in this codebase)."""

    def __init__(self, detail: str) -> None:
        super().__init__(ErrorCode.VALIDATION_ERROR, detail)
