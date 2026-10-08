from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from services.rinex_service.cache import RINEXCache, RINEXCacheError


def test_cache_is_content_addressed_and_idempotent(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    content = b"     3.03           NAVIGATION DATA     M                   RINEX VERSION / TYPE\n"
    first = cache.store_bytes(content, original_name="BRDC00IGS_R_20262700000_01D_MN.rnx")
    second = cache.store_bytes(content, original_name="different-name.rnx")
    assert first.sha256 == hashlib.sha256(content).hexdigest()
    assert second.sha256 == first.sha256
    assert second.path == first.path
    assert cache.resolve(first.sha256).path == first.path


def test_cache_rejects_checksum_mismatch(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    with pytest.raises(RINEXCacheError, match="sha256 mismatch"):
        cache.store_bytes(b"rinex", original_name="x.rnx", expected_sha256="0" * 64)


def test_cache_sanitizes_provider_filename(tmp_path: Path):
    artifact = RINEXCache(tmp_path).store_bytes(b"rinex", original_name="../../secret/../nav file?.rnx")
    assert artifact.path.parent.parent.parent == tmp_path.resolve()
    assert artifact.path.name == "nav_file_.rnx"


def test_cache_detects_corruption(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    artifact = cache.store_bytes(b"valid", original_name="nav.rnx")
    artifact.path.write_bytes(b"corrupt")
    with pytest.raises(RINEXCacheError, match="corruption"):
        cache.resolve(artifact.sha256)
