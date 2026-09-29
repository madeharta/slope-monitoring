from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
import httpx
from services.rinex_service.cache import CachedRINEXArtifact, RINEXCache, RINEXCacheError
from services.rinex_service.parser import RINEXParseError, parse_rinex_bytes


class PublicRINEXDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicNavigationSource:
    name: str
    host: str
    url_template: str

    def url_for(self, observed_at: datetime) -> str:
        timestamp = _as_utc(observed_at)
        year = timestamp.year
        doy = timestamp.timetuple().tm_yday
        yy = year % 100
        return self.url_template.format(year=year, doy=doy, doy3=f"{doy:03d}", yy=f"{yy:02d}")


BKG_WRD = PublicNavigationSource(
    name="BKG_WRD",
    host="igs.bkg.bund.de",
    url_template=(
        "https://igs.bkg.bund.de/root_ftp/IGS/BRDC/{year}/{doy3}/"
        "BRDC00WRD_S_{year}{doy3}0000_01D_MN.rnx.gz"
    ),
)
BKG_IGS = PublicNavigationSource(
    name="BKG_IGS",
    host="igs.bkg.bund.de",
    url_template=(
        "https://igs.bkg.bund.de/root_ftp/IGS/BRDC/{year}/{doy3}/"
        "BRDC00IGS_R_{year}{doy3}0000_01D_MN.rnx.gz"
    ),
)
CDDIS_IGS = PublicNavigationSource(
    name="CDDIS_IGS",
    host="cddis.nasa.gov",
    url_template=(
        "https://cddis.nasa.gov/archive/gnss/data/daily/{year}/brdc/"
        "BRDC00IGS_R_{year}{doy3}0000_01D_MN.rnx.gz"
    ),
)
DEFAULT_PUBLIC_NAV_SOURCES = (BKG_WRD, BKG_IGS, CDDIS_IGS)


class PublicRINEXNavigationProvider:
    def __init__(
        self,
        cache: RINEXCache,
        source: PublicNavigationSource,
        *,
        timeout_s: float | None = None,
        max_bytes: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache = cache
        self.source = source
        self.timeout_s = timeout_s or float(os.getenv("RINEX_DOWNLOAD_TIMEOUT_S", "60"))
        self.max_bytes = max_bytes or int(
            os.getenv("RINEX_DOWNLOAD_MAX_BYTES", str(250 * 1024 * 1024))
        )
        self._client = client

    def fetch(self, observed_at: datetime) -> CachedRINEXArtifact:
        timestamp = _as_utc(observed_at)
        current_url = self._validate_url(self.source.url_for(timestamp))
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_s, follow_redirects=False)
        try:
            for _ in range(4):
                with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise PublicRINEXDownloadError(
                                f"{self.source.name} redirect response did not include Location"
                            )
                        current_url = self._validate_url(urljoin(current_url, location))
                        continue
                    if response.status_code != 200:
                        raise PublicRINEXDownloadError(
                            f"{self.source.name} download failed with HTTP {response.status_code}"
                        )
                    content = self._read_bounded(response)
                    if self._looks_like_html(content, response.headers.get("content-type", "")):
                        raise PublicRINEXDownloadError(
                            f"{self.source.name} returned HTML instead of a RINEX navigation artifact"
                        )
                    name = Path(urlparse(current_url).path).name or "broadcast-nav.rnx.gz"
                    try:
                        metadata = parse_rinex_bytes(content, original_name=name)
                    except RINEXParseError as exc:
                        raise PublicRINEXDownloadError(
                            f"{self.source.name} returned invalid RINEX content: {exc}"
                        ) from exc
                    if metadata.data_type != "navigation":
                        raise PublicRINEXDownloadError(
                            f"{self.source.name} returned RINEX {metadata.data_type}, expected navigation"
                        )
                    if metadata.nominal_date != timestamp.date():
                        actual = metadata.nominal_date.isoformat() if metadata.nominal_date else "unknown"
                        raise PublicRINEXDownloadError(
                            f"{self.source.name} returned navigation for {actual}, expected {timestamp.date().isoformat()}"
                        )
                    if metadata.record_first_epoch_utc and metadata.record_last_epoch_utc:
                        if not (
                            metadata.record_first_epoch_utc.date()
                            <= timestamp.date()
                            <= metadata.record_last_epoch_utc.date()
                        ):
                            raise PublicRINEXDownloadError(
                                f"{self.source.name} navigation records do not cover UTC date {timestamp.date().isoformat()}"
                            )
                    try:
                        return self.cache.store_bytes(
                            content,
                            original_name=name,
                            source_url=self._redacted_source_url(current_url),
                            metadata={
                                "provider": self.source.name,
                                "final_host": self.source.host,
                                "public_broadcast_navigation": True,
                            },
                        )
                    except RINEXCacheError as exc:
                        raise PublicRINEXDownloadError(str(exc)) from exc
            raise PublicRINEXDownloadError(f"too many redirects from {self.source.name}")
        except httpx.HTTPError as exc:
            raise PublicRINEXDownloadError(f"{self.source.name} request failed: {exc}") from exc
        finally:
            if owns_client:
                client.close()

    def _read_bounded(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                advertised_size = int(content_length)
            except ValueError:
                advertised_size = None
            if advertised_size is not None and advertised_size > self.max_bytes:
                raise PublicRINEXDownloadError(
                    f"{self.source.name} artifact exceeds configured limit of {self.max_bytes} bytes"
                )
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise PublicRINEXDownloadError(
                    f"{self.source.name} artifact exceeds configured limit of {self.max_bytes} bytes"
                )
            chunks.append(chunk)
        content = b"".join(chunks)
        if not content:
            raise PublicRINEXDownloadError(f"{self.source.name} returned an empty artifact")
        return content

    def _validate_url(self, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme.lower() != "https":
            raise PublicRINEXDownloadError("public RINEX URL must use HTTPS")
        if parsed.hostname is None or parsed.hostname.lower() != self.source.host:
            raise PublicRINEXDownloadError(
                f"public RINEX host must be exactly {self.source.host} for {self.source.name}"
            )
        if parsed.username is not None or parsed.password is not None:
            raise PublicRINEXDownloadError("credentials must not be embedded in public RINEX URLs")
        if parsed.port not in {None, 443}:
            raise PublicRINEXDownloadError("non-standard public RINEX URL port is not allowed")
        if parsed.fragment:
            parsed = parsed._replace(fragment="")
        return urlunparse(parsed)

    @staticmethod
    def _looks_like_html(content: bytes, media_type: str) -> bool:
        if "text/html" in media_type.lower():
            return True
        head = content[:512].lstrip().lower()
        return head.startswith(b"<!doctype html") or head.startswith(b"<html")

    @staticmethod
    def _redacted_source_url(value: str) -> str:
        parsed = urlparse(value)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise PublicRINEXDownloadError("observed_at must be timezone-aware")
    return value.astimezone(timezone.utc)
