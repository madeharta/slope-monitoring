from __future__ import annotations
import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path
import pytest
from services.rinex_service.cache import RINEXCache, RINEXCacheError
from services.rinex_service.normalizer import RINEXNormalizationError, normalize_rinex_transport
from services.rinex_service.parser import parse_rinex_bytes
from services.rinex_service.resolver import RINEXNavigationResolver, RINEXResolutionError


def _nav_payload(*, station: str = "CLBG", mixed: bool = False, hour: int = 0) -> bytes:
    system = "M" if mixed else "G"
    phrase = "MIXED" if mixed else "GPS"
    return (
        f"     3.05           NAVIGATION DATA     {system} ({phrase})             RINEX VERSION / TYPE\n"
        f"{station:<60}MARKER NAME\n"
        f"{'':60}END OF HEADER\n"
        f"G01 2026 09 25 {hour:02d} 00 00 0 0 0\n"
    ).encode()


def _obs_payload(*, station: str = "CLBG") -> bytes:
    return (
        "     3.05           OBSERVATION DATA    G                   RINEX VERSION / TYPE\n"
        f"{station:<60}MARKER NAME\n"
        "  2026     9    25     0     0    0.0000000     GPS         TIME OF FIRST OBS\n"
        f"{'':60}END OF HEADER\n"
    ).encode()


def _compact_obs_payload() -> bytes:
    return (
        "3.0                 COMPACT RINEX FORMAT                    CRINEX VERS   / TYPE\n"
        "RNX2CRX ver.4.0.7                       27-Sep-26 08:59     CRINEX PROG / DATE\n"
        "     3.05           OBSERVATION DATA    M                   RINEX VERSION / TYPE\n"
        f"{'CLBG':<60}MARKER NAME\n"
        "  2026     9    25     0     0    0.0000000     GPS         TIME OF FIRST OBS\n"
        f"{'':60}END OF HEADER\n"
    ).encode()


def test_content_header_wins_over_misleading_observation_extension():
    metadata = parse_rinex_bytes(_nav_payload(), original_name="clbg2680.26o")
    assert metadata.data_type == "navigation"
    assert metadata.nominal_date == date(2026, 9, 25)


def test_generic_rnx_and_extensionless_files_are_classified_from_content():
    generic = parse_rinex_bytes(_nav_payload(), original_name="download.rnx")
    extensionless = parse_rinex_bytes(_nav_payload(), original_name="download")
    assert generic.data_type == "navigation"
    assert extensionless.data_type == "navigation"
    assert generic.station == "CLBG"
    assert extensionless.station == "CLBG"


def test_hatanaka_compact_header_is_observation_even_with_nav_like_filename():
    metadata = parse_rinex_bytes(_compact_obs_payload(), original_name="clbg2680.26n")
    assert metadata.data_type == "observation"
    assert metadata.container_format == "compact_rinex"
    assert metadata.station == "CLBG"


@pytest.mark.parametrize("name", ["clbg2680.26d", "CLBG00IDN_R_20262680000_01D_30S_MO.crx"])
def test_hatanaka_legacy_and_crx_names_are_detected_from_compact_header(name: str):
    metadata = parse_rinex_bytes(_compact_obs_payload(), original_name=name)
    assert metadata.data_type == "observation"
    assert metadata.container_format == "compact_rinex"


def test_gzip_payload_is_decompressed_by_magic_not_extension():
    compressed = gzip.compress(_nav_payload())
    metadata = parse_rinex_bytes(compressed, original_name="opaque.bin")
    assert metadata.data_type == "navigation"
    assert metadata.transport_compression == "gzip"
    assert metadata.station == "CLBG"


def test_gzip_output_limit_blocks_oversized_decompression():
    compressed = gzip.compress(b"A" * (2 * 1024 * 1024))
    with pytest.raises(RINEXNormalizationError, match="safe decompression limit"):
        normalize_rinex_transport(
            compressed,
            max_decompressed_bytes=1024 * 1024,
            max_expansion_ratio=1000,
        )


def test_gzip_expansion_ratio_blocks_large_ratio():
    compressed = gzip.compress(b"A" * (2 * 1024 * 1024))
    with pytest.raises(RINEXNormalizationError, match="safe decompression limit"):
        normalize_rinex_transport(
            compressed,
            max_decompressed_bytes=16 * 1024 * 1024,
            max_expansion_ratio=2,
        )


def test_unix_compress_magic_uses_normalization_path(monkeypatch: pytest.MonkeyPatch):
    import services.rinex_service.normalizer as normalizer
    expected = _nav_payload()
    monkeypatch.setattr(
        normalizer,
        "_decompress_unix_compress",
        lambda content, max_bytes, ratio, timeout_s: expected,
    )
    result = normalizer.normalize_rinex_transport(b"\x1f\x9dsynthetic")
    assert result.content == expected
    assert result.transport_compression == "compress-z"


def test_cache_blocks_unsafe_compressed_artifact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("RINEX_DECOMPRESS_MAX_BYTES", "1048576")
    monkeypatch.setenv("RINEX_DECOMPRESS_MAX_RATIO", "1000")
    compressed = gzip.compress(b"A" * (2 * 1024 * 1024))
    with pytest.raises(RINEXCacheError, match="unsafe compressed RINEX artifact"):
        RINEXCache(tmp_path).store_bytes(compressed, original_name="bomb.rnx.gz")
    assert not list(tmp_path.glob("*/*/manifest.json"))


def test_resolver_requires_exact_station_when_filter_is_requested(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    cache.store_bytes(_nav_payload(station="CLBG"), original_name="clbg2680.26n")
    with pytest.raises(RINEXResolutionError, match="station XXXX"):
        RINEXNavigationResolver(cache).resolve(
            datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="XXXX"
        )


def test_resolver_does_not_treat_record_bounds_as_navigation_validity(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    artifact = cache.store_bytes(_nav_payload(hour=10), original_name="clbg2680.26n")
    resolved = RINEXNavigationResolver(cache).resolve(
        datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG"
    )
    assert resolved.artifact.sha256 == artifact.sha256
    assert resolved.metadata.record_last_epoch_utc.hour == 10
    assert resolved.metadata.navigation_valid_from_utc is None
    assert resolved.metadata.navigation_valid_until_utc is None


def test_resolver_ignores_gzip_observation_candidate(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    cache.store_bytes(gzip.compress(_obs_payload()), original_name="clbg2680.26o.gz")
    with pytest.raises(RINEXResolutionError, match="no cached"):
        RINEXNavigationResolver(cache).resolve(
            datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG"
        )


def test_resolver_old_manifest_epoch_keys_remain_compatible(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    artifact = cache.store_bytes(_nav_payload(), original_name="clbg2680.26n")
    manifest = json.loads(artifact.manifest_path.read_text())
    rinex = manifest["metadata"]["rinex"]
    rinex["first_epoch_utc"] = rinex.pop("record_first_epoch_utc")
    rinex["last_epoch_utc"] = rinex.pop("record_last_epoch_utc")
    rinex.pop("navigation_valid_from_utc")
    rinex.pop("navigation_valid_until_utc")
    rinex.pop("container_format")
    rinex.pop("transport_compression")
    artifact.manifest_path.write_text(json.dumps(manifest))
    resolved = RINEXNavigationResolver(cache).resolve(
        datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG"
    )
    assert resolved.metadata.record_first_epoch_utc.date() == date(2026, 9, 25)
    assert resolved.metadata.container_format == "rinex"
    assert resolved.metadata.transport_compression == "none"


def test_resolver_ranking_is_deterministic_for_equivalent_candidates(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    first = cache.store_bytes(_nav_payload(hour=0), original_name="a.rnx")
    second = cache.store_bytes(_nav_payload(hour=1), original_name="b.rnx")
    resolved = RINEXNavigationResolver(cache).resolve(
        datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG"
    )
    assert resolved.artifact.sha256 == max(first.sha256, second.sha256)

def test_unix_compress_external_path_is_bounded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import services.rinex_service.normalizer as normalizer
    fake = tmp_path / "gzip"
    fake.write_text("#!/bin/sh\nprintf 'synthetic-output'\n")
    fake.chmod(0o755)
    monkeypatch.setattr(normalizer.shutil, "which", lambda name: str(fake) if name == "gzip" else None)
    result = normalizer._decompress_unix_compress(
        b"\x1f\x9dsynthetic",
        max_bytes=1024,
        ratio=1000,
        timeout_s=2,
    )
    assert result == b"synthetic-output"


def test_unix_compress_external_output_limit_is_enforced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import services.rinex_service.normalizer as normalizer
    fake = tmp_path / "gzip"
    fake.write_text("#!/bin/sh\nhead -c 2097152 /dev/zero\n")
    fake.chmod(0o755)
    monkeypatch.setattr(normalizer.shutil, "which", lambda name: str(fake) if name == "gzip" else None)
    with pytest.raises(RINEXNormalizationError, match="safe decompression limit"):
        normalizer._decompress_unix_compress(
            b"\x1f\x9dsynthetic",
            max_bytes=1024 * 1024,
            ratio=1000,
            timeout_s=2,
        )


def test_nested_compression_layer_limit_is_enforced():
    payload = _nav_payload()
    nested = gzip.compress(gzip.compress(gzip.compress(payload)))
    with pytest.raises(RINEXNormalizationError, match="nesting exceeds"):
        normalize_rinex_transport(
            nested,
            max_decompressed_bytes=16 * 1024 * 1024,
            max_expansion_ratio=1000,
            max_layers=2,
        )
