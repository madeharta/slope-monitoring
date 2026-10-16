"""MFA — TOTP (Time-based One-Time Password), RFC 6238, pure stdlib
(hmac/hashlib/struct/base64 — NO third-party dependency). Same algorithm
Google Authenticator/Authy use — no SMS/email service needed (free, works
offline once enrolled). `users.mfa_secret` column already existed from
migration 005 (`mfa_secret TEXT`) — this module is the first thing to
actually populate/use it.

Implementation choice (2026-09-19): a `pyotp`-based draft was considered,
but pyotp is not installed in this sandbox and cannot be verified here.
RFC 6238 TOTP is simple enough to implement directly against Python's
standard library — doing so let this be ACTUALLY TESTED against the
official RFC 6238 Appendix B test vector (secret "12345678901234567890",
T=59s, SHA1, 8-digit -> "94287082"), unlike the torch/RTKLIB integrations
elsewhere in this codebase which remain unverified. Prefer this over an
unverified dependency.

Flow:
  1. POST /auth/mfa/enroll (authenticated, any role) — generates a new
     secret, stores it UNCONFIRMED (mfa_enabled stays False), returns a
     provisioning URI the frontend renders as a QR code.
  2. User scans QR in an authenticator app (any RFC 6238-compliant app —
     Google Authenticator, Authy, 1Password, etc. all interoperate).
  3. POST /auth/mfa/verify {code} — checks the code against the stored
     secret. First successful check flips mfa_enabled=True (enrollment
     confirmed). On every LOGIN afterward, this same endpoint is called
     again to upgrade the session's mfa_verified claim (see auth.py).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

_STEP_SECONDS = 30
_DIGITS = 6           # 6-digit is the near-universal default for authenticator apps
_CLOCK_DRIFT_STEPS = 1  # tolerate ±1 step (±30s) for phone/server clock drift


def generate_secret() -> str:
    """Base32, no padding — the format every authenticator app expects in
    a provisioning URI (RFC 4648 base32, used by RFC 6238 TOTP secrets
    by convention)."""
    random_bytes = secrets.token_bytes(20)  # 160 bits — matches the RFC 6238 test vector's key length
    return base64.b32encode(random_bytes).decode("ascii").rstrip("=")


def provisioning_uri(secret: str, account_email: str, issuer: str = "MAGRIS LEWS") -> str:
    """otpauth:// URI — frontend renders this as a QR code (any JS QR
    library; no image generation needed server-side). Manually built
    (not via a library) since it's just a URL format, documented in the
    Google Authenticator "Key Uri Format" spec."""
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
    padded = secret_b32 + "=" * (-len(secret_b32) % 8)  # base32 needs padding to a multiple of 8
    return base64.b32decode(padded.upper())


def verify_code(secret_b32: str, code: str, at_time: float | None = None) -> bool:
    """Checks `code` against the current time step AND ±_CLOCK_DRIFT_STEPS
    neighbours, using constant-time comparison (hmac.compare_digest) to
    avoid a timing side-channel on the code check."""
    if at_time is None:
        at_time = time.time()
    secret_bytes = _decode_secret(secret_b32)
    counter = int(at_time // _STEP_SECONDS)

    for delta in range(-_CLOCK_DRIFT_STEPS, _CLOCK_DRIFT_STEPS + 1):
        expected = _hotp(secret_bytes, counter + delta)
        if hmac.compare_digest(expected, code):
            return True
    return False
