from __future__ import annotations

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    role: str


class MFAEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str  # frontend renders this as a QR code


class MFAVerifyRequest(BaseModel):
    code: str


class MFAVerifyResponse(BaseModel):
    ok: bool
    mfa_enabled: bool           # True once this was the FIRST successful verify (enrollment confirmed)
    access_token: str | None = None  # present when this call upgraded an existing session's mfa_verified claim


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str  # rotated — best practice, old refresh token becomes unusable next time
