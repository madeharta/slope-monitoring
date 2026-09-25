from __future__ import annotations
from enum import Enum
class ErrorCode(str, Enum):
    INVALID_DEVICE_ID = "INVALID_DEVICE_ID"
    MISSING_HEADER = "MISSING_HEADER"
    INVALID_CSV = "INVALID_CSV"
    INVALID_BASE64 = "INVALID_BASE64"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN_ROLE = "FORBIDDEN_ROLE"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MODEL_INCOMPATIBLE = "MODEL_INCOMPATIBLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
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
    def __init__(self, code: ErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        self.status_code = STATUS_FOR[code]
        super().__init__(f"{code.value}: {detail}")
    def to_envelope(self) -> dict:
        return {"ok": False, "error": self.code.value, "detail": self.detail}
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
    def __init__(self, model_type: str, version_id: str, reason: str) -> None:
        super().__init__(
            ErrorCode.MODEL_INCOMPATIBLE,
            f"model '{model_type}:{version_id}' failed compatibility check: {reason}",
        )
class ModelTypeUnavailableError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(ErrorCode.VALIDATION_ERROR, detail)
