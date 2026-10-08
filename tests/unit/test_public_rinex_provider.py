from __future__ import annotations
import gzip
from datetime import datetime, timezone
from pathlib import Path
import httpx
import pytest
from services.rinex_service.acquisition import RINEXAcquisitionError, RINEXNavigationAcquisition
from services.rinex_service.cache import RINEXCache
from services.rinex_service.parser import parse_rinex_bytes
from services.rinex_service.public_provider import (
    BKG_WRD,
    PublicNavigationSource,
    PublicRINEXDownloadError,
    PublicRINEXNavigationProvider,
)
from services.rinex_service.resolver import RINEXNavigationResolver


def _nav_payload(day: int = 25) -> bytes:
    return (
        "     3.05           NAVIGATION DATA     M                   RINEX VERSION / TYPE\n"
        f"{'':60}END OF HEADER\n"
        f"G01 2026  9 {day:2d}  0  0  0.0  0.0 0.0 0.0\n"
    ).encode()


def _obs_payload() -> bytes:
    return (
        "     3.05           OBSERVATION DATA    M                   RINEX VERSION / TYPE\n"
        f"{'CLBG':<60}MARKER NAME\n"
        "  2026     9    25     0     0    0.0000000     GPS         TIME OF FIRST OBS\n"
        f"{'':60}END OF HEADER\n"
    ).encode()


def _provider(tmp_path: Path, handler, source=BKG_WRD):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return PublicRINEXNavigationProvider(RINEXCache(tmp_path), source, client=client), client


def test_bkg_url_is_deterministic_from_utc_date():
    url = BKG_WRD.url_for(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    assert url == (
        "https://igs.bkg.bund.de/root_ftp/IGS/BRDC/2026/268/"
        "BRDC00WRD_S_20262680000_01D_MN.rnx.gz"
    )


def test_public_provider_downloads_valid_mixed_navigation(tmp_path: Path):
    payload = gzip.compress(_nav_payload())
    provider, client = _provider(tmp_path, lambda request: httpx.Response(200, content=payload))
    try:
        artifact = provider.fetch(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    finally:
        client.close()
    metadata = parse_rinex_bytes(artifact.path.read_bytes(), original_name=artifact.original_name)
    assert metadata.data_type == "navigation"
    assert metadata.nominal_date.isoformat() == "2026-09-25"
    assert metadata.station is None
    assert artifact.source_url.startswith("https://igs.bkg.bund.de/")


def test_public_product_is_global_and_satisfies_station_filtered_resolver(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    cache.store_bytes(
        gzip.compress(_nav_payload()),
        original_name="BRDC00WRD_S_20262680000_01D_MN.rnx.gz",
        metadata={"provider": "BKG_WRD", "public_broadcast_navigation": True},
    )
    resolved = RINEXNavigationResolver(cache).resolve(
        datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG"
    )
    assert resolved.metadata.station is None
    assert resolved.metadata.constellation == "MIXED"


def test_station_specific_candidate_beats_global_candidate(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    global_artifact = cache.store_bytes(
        gzip.compress(_nav_payload()),
        original_name="BRDC00WRD_S_20262680000_01D_MN.rnx.gz",
    )
    specific_payload = (
        "     2.11           NAVIGATION DATA     GPS                 RINEX VERSION / TYPE\n"
        f"{'CLBG':<60}MARKER NAME\n"
        f"{'':60}END OF HEADER\n"
        " 1 26  9 25  0  0  0.0  0.0 0.0 0.0\n"
    ).encode()
    specific = cache.store_bytes(specific_payload, original_name="clbg2680.26n")
    resolved = RINEXNavigationResolver(cache).resolve(
        datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG"
    )
    assert resolved.artifact.sha256 == specific.sha256
    assert resolved.artifact.sha256 != global_artifact.sha256


def test_public_provider_rejects_html(tmp_path: Path):
    provider, client = _provider(
        tmp_path,
        lambda request: httpx.Response(200, content=b"<html>login</html>", headers={"content-type": "text/html"}),
    )
    try:
        with pytest.raises(PublicRINEXDownloadError, match="HTML"):
            provider.fetch(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    finally:
        client.close()


def test_public_provider_rejects_observation_file(tmp_path: Path):
    provider, client = _provider(tmp_path, lambda request: httpx.Response(200, content=gzip.compress(_obs_payload())))
    try:
        with pytest.raises(PublicRINEXDownloadError, match="expected navigation"):
            provider.fetch(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    finally:
        client.close()


def test_public_provider_rejects_wrong_day(tmp_path: Path):
    provider, client = _provider(tmp_path, lambda request: httpx.Response(200, content=gzip.compress(_nav_payload(day=24))))
    try:
        with pytest.raises(PublicRINEXDownloadError, match="do not cover UTC date 2026-09-25"):
            provider.fetch(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    finally:
        client.close()


def test_public_provider_blocks_cross_host_redirect(tmp_path: Path):
    provider, client = _provider(
        tmp_path,
        lambda request: httpx.Response(302, headers={"location": "https://evil.example/nav.rnx.gz"}),
    )
    try:
        with pytest.raises(PublicRINEXDownloadError, match="host must be exactly"):
            provider.fetch(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    finally:
        client.close()


def test_acquisition_cache_hit_avoids_provider_factory(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    cache.store_bytes(gzip.compress(_nav_payload()), original_name="BRDC00WRD_S_20262680000_01D_MN.rnx.gz")
    calls = []
    acquisition = RINEXNavigationAcquisition(
        cache,
        provider_factory=lambda source: calls.append(source),
    )
    result = acquisition.ensure(datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG")
    assert result.cache_hit is True
    assert result.provider is None
    assert calls == []


def test_acquisition_falls_back_to_second_provider(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    first = PublicNavigationSource("FIRST", "first.example", "https://first.example/{year}/{doy3}.rnx.gz")
    second = PublicNavigationSource("SECOND", "second.example", "https://second.example/{year}/{doy3}.rnx.gz")
    calls = []

    class FakeProvider:
        def __init__(self, source):
            self.source = source
        def fetch(self, observed_at):
            calls.append(self.source.name)
            if self.source.name == "FIRST":
                raise PublicRINEXDownloadError("unavailable")
            return cache.store_bytes(
                gzip.compress(_nav_payload()),
                original_name="BRDC00WRD_S_20262680000_01D_MN.rnx.gz",
                metadata={"provider": self.source.name, "public_broadcast_navigation": True},
            )

    acquisition = RINEXNavigationAcquisition(
        cache,
        sources=(first, second),
        provider_factory=lambda source: FakeProvider(source),
    )
    result = acquisition.ensure(datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG")
    assert result.cache_hit is False
    assert result.provider == "SECOND"
    assert calls == ["FIRST", "SECOND"]


def test_acquisition_reports_all_provider_failures(tmp_path: Path):
    cache = RINEXCache(tmp_path)
    source = PublicNavigationSource("FAIL", "fail.example", "https://fail.example/{year}/{doy3}.rnx.gz")

    class FailedProvider:
        def fetch(self, observed_at):
            raise PublicRINEXDownloadError("offline")

    acquisition = RINEXNavigationAcquisition(
        cache,
        sources=(source,),
        provider_factory=lambda source: FailedProvider(),
    )
    with pytest.raises(RINEXAcquisitionError, match="FAIL: offline"):
        acquisition.ensure(datetime(2026, 9, 25, 12, tzinfo=timezone.utc), station="CLBG")
