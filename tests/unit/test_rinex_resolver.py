from datetime import datetime, timezone
from pathlib import Path
import pytest
from services.rinex_service.cache import RINEXCache
from services.rinex_service.resolver import RINEXNavigationResolver, RINEXResolutionError
def _nav(station: str, date_fields: str, *, mixed: bool = False) -> bytes:
    system = "M" if mixed else "G"
    phrase = "MIXED" if mixed else "GPS"
    header = (
        f"     3.05           NAVIGATION DATA     {system}                   RINEX VERSION / TYPE\n"
        f"{station:<60}MARKER NAME\n"
        f"{'':60}END OF HEADER\n"
    )
    return (header + f"G01 {date_fields} 0 0 0\n").encode()
def test_resolver_selects_same_utc_day(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    expected = cache.store_bytes(_nav("CLBG", "2026 09 27 00 00 00"), original_name="clbg2700.26n")
    cache.store_bytes(_nav("CLBG", "2026 09 26 00 00 00"), original_name="clbg2690.26n")
    resolved = RINEXNavigationResolver(cache).resolve(datetime(2026, 9, 27, 12, tzinfo=timezone.utc))
    assert resolved.artifact.sha256 == expected.sha256
def test_resolver_station_filter(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    clbg = cache.store_bytes(_nav("CLBG", "2026 09 27 00 00 00"), original_name="clbg2700.26n")
    cache.store_bytes(_nav("OTHER", "2026 09 27 00 00 00"), original_name="othr2700.26n")
    resolved = RINEXNavigationResolver(cache).resolve(
        datetime(2026, 9, 27, 12, tzinfo=timezone.utc), station="clbg"
    )
    assert resolved.artifact.sha256 == clbg.sha256
def test_resolver_prefers_mixed_navigation(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    cache.store_bytes(_nav("CLBG", "2026 09 27 00 00 00"), original_name="clbg2700.26n")
    mixed = cache.store_bytes(_nav("CLBG", "2026 09 27 00 00 00", mixed=True), original_name="BRDC00IGS_R_20262700000_01D_MN.rnx")
    resolved = RINEXNavigationResolver(cache).resolve(datetime(2026, 9, 27, 12, tzinfo=timezone.utc))
    assert resolved.artifact.sha256 == mixed.sha256
def test_resolver_ignores_observation(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    obs = (
        "     2.11           OBSERVATION DATA    G                   RINEX VERSION / TYPE\n"
        f"{'CLBG':<60}MARKER NAME\n"
        f"{'':60}END OF HEADER\n"
    ).encode()
    cache.store_bytes(obs, original_name="clbg2700.26o")
    with pytest.raises(RINEXResolutionError, match="no cached"):
        RINEXNavigationResolver(cache).resolve(datetime(2026, 9, 27, tzinfo=timezone.utc))
def test_resolver_rejects_naive_timestamp(tmp_path: Path):
    with pytest.raises(RINEXResolutionError, match="timezone-aware"):
        RINEXNavigationResolver(RINEXCache(tmp_path)).resolve(datetime(2026, 9, 27))
