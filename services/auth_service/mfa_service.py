from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
import struct
import time
_STEP_SECONDS = 30
_DIGITS = 6
_CLOCK_DRIFT_STEPS = 1
def generate_secret() -> str:
    random_bytes = secrets.token_bytes(20)
    return base64.b32encode(random_bytes).decode("ascii").rstrip("=")
def provisioning_uri(secret: str, account_email: str, issuer: str = "MAGRIS LEWS") -> str:
    from urllib.parse import quote
    label = quote(f"{issuer}:{account_email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={_DIGITS}&period={_STEP_SECONDS}"
def _hotp(secret_bytes: bytes, counter: int) -> str:
    msg = struct.pack(">Q", counter)
    h = hmac.new(secret_bytes, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = (struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**_DIGITS)
    return str(code).zfill(_DIGITS)
def _decode_secret(secret_b32: str) -> bytes:
    padded = secret_b32 + "=" * (-len(secret_b32) % 8)
    return base64.b32decode(padded.upper())
def verify_code(secret_b32: str, code: str, at_time: float | None = None) -> bool:
    if at_time is None:
        at_time = time.time()
    secret_bytes = _decode_secret(secret_b32)
    counter = int(at_time // _STEP_SECONDS)
    for delta in range(-_CLOCK_DRIFT_STEPS, _CLOCK_DRIFT_STEPS + 1):
        expected = _hotp(secret_bytes, counter + delta)
        if hmac.compare_digest(expected, code):
            return True
    return False
