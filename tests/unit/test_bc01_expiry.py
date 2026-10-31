from datetime import datetime, timedelta, timezone
from services.device_config_service.blast_expiry import expired

T = datetime(2026, 10, 29, 9, 53, 18, tzinfo=timezone.utc)

def test_before_deadline():
    assert not expired(T, 1, T + timedelta(seconds=59))

def test_exact_deadline():
    assert expired(T, 1, T + timedelta(seconds=60))

def test_after_deadline():
    assert expired(T, 1, T + timedelta(seconds=61))

def test_invalid_or_missing_timeout_fails_closed():
    for value in (None, 0, -1, 'invalid', True):
        assert expired(T, value, T)

def test_missing_and_naive_timestamp_fails_closed():
    assert expired(None, 1, T)
    assert expired(T.replace(tzinfo=None), 1, T)

def test_new_start_has_independent_deadline():
    assert expired(T, 1, T + timedelta(seconds=70))
    assert not expired(T + timedelta(seconds=50), 1, T + timedelta(seconds=70))
