import gzip
import io

import pytest
import datetime as dt
import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2]/'scripts'/'ppk_qa_scheduler.py'
spec = importlib.util.spec_from_file_location('ppk_qa_scheduler', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_closed_windows_with_grace():
    now = dt.datetime(2026, 10, 19, 11, 28, tzinfo=dt.timezone.utc)
    result = module.windows(now, 20, 3)
    assert result == [
        (dt.datetime(2026,10,19,8,tzinfo=dt.timezone.utc),dt.datetime(2026,10,19,9,tzinfo=dt.timezone.utc)),
        (dt.datetime(2026,10,19,9,tzinfo=dt.timezone.utc),dt.datetime(2026,10,19,10,tzinfo=dt.timezone.utc)),
        (dt.datetime(2026,10,19,10,tzinfo=dt.timezone.utc),dt.datetime(2026,10,19,11,tzinfo=dt.timezone.utc)),
    ]


def test_invalid_grace_fails_closed():
    try:
        module.windows(dt.datetime.now(dt.timezone.utc), 0, 3)
        assert False
    except ValueError:
        pass


def test_bounded_nav_decompress_valid():
    assert module.bounded_nav_decompress(gzip.compress(b'valid-data')) == b'valid-data'


def test_bounded_nav_decompress_rejects_compressed_size(monkeypatch):
    monkeypatch.setattr(module, 'MAX_NAV_GZIP_BYTES', 5)
    with pytest.raises(ValueError, match='compressed size'):
        module.bounded_nav_decompress(gzip.compress(b'valid'))


def test_bounded_nav_decompress_rejects_expansion_bomb(monkeypatch):
    monkeypatch.setattr(module, 'MAX_NAV_EXPANDED_BYTES', 128)
    with pytest.raises(ValueError, match='expanded size'):
        module.bounded_nav_decompress(gzip.compress(b'A' * 4096))


def test_bounded_nav_decompress_rejects_truncated_gzip():
    with pytest.raises(ValueError, match='corrupt or truncated'):
        module.bounded_nav_decompress(gzip.compress(b'nav-data')[:-5])
