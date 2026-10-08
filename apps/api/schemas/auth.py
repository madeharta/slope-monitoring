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
    provisioning_uri: str
class MFAVerifyRequest(BaseModel):
    code: str
class MFAVerifyResponse(BaseModel):
    ok: bool
    mfa_enabled: bool
    access_token: str | None = None
class RefreshRequest(BaseModel):
    refresh_token: str
class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
