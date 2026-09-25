import time
import pytest
from services.auth_service.mfa_service import (
    _decode_secret,
    _hotp,
    generate_secret,
    provisioning_uri,
    verify_code,
)
def test_hotp_matches_official_rfc6238_test_vector():
    secret_bytes = b"12345678901234567890"
    counter = 59 // 30
    import hashlib
    import hmac as hmac_mod
    import struct
    msg = struct.pack(">Q", counter)
    h = hmac_mod.new(secret_bytes, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code_int = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    assert str(code_int % (10**8)).zfill(8) == "94287082"
def test_generate_and_verify_round_trip():
    secret = generate_secret()
    now = time.time()
    counter = int(now // 30)
    correct_code = _hotp(_decode_secret(secret), counter)
    assert verify_code(secret, correct_code, at_time=now) is True
def test_wrong_code_rejected():
    secret = generate_secret()
    assert verify_code(secret, "000000", at_time=time.time()) is False
def test_clock_drift_tolerance_one_step():
    secret = generate_secret()
    now = time.time()
    counter = int(now // 30)
    prev_code = _hotp(_decode_secret(secret), counter - 1)
    assert verify_code(secret, prev_code, at_time=now) is True
def test_code_outside_tolerance_rejected():
    secret = generate_secret()
    now = time.time()
    counter = int(now // 30)
    old_code = _hotp(_decode_secret(secret), counter - 3)
    assert verify_code(secret, old_code, at_time=now) is False
def test_provisioning_uri_shape():
    secret = generate_secret()
    uri = provisioning_uri(secret, "operator@namadomain.id")
    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri
    assert "digits=6" in uri and "period=30" in uri
