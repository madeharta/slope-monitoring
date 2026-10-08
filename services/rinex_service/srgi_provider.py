from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlunparse
import httpx
from services.rinex_service.cache import CachedRINEXArtifact, RINEXCache, RINEXCacheError
class RINEXDownloadError(RuntimeError):
    pass
class SRGIRINEXProvider:
    ALLOWED_HOST = "srgi.big.go.id"
    def __init__(
        self,
        cache: RINEXCache,
        *,
        timeout_s: float | None = None,
        max_bytes: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache = cache
        self.timeout_s = timeout_s or float(os.getenv("RINEX_DOWNLOAD_TIMEOUT_S", "60"))
        self.max_bytes = max_bytes or int(os.getenv("RINEX_DOWNLOAD_MAX_BYTES", str(250 * 1024 * 1024)))
        self._client = client
    def fetch(
        self,
        url: str,
        *,
        expected_sha256: str | None = None,
    ) -> CachedRINEXArtifact:
        current_url = self._validate_url(url)
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_s, follow_redirects=False)
        try:
            for _ in range(4):
                with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise RINEXDownloadError("SRGI redirect response did not include Location")
                        current_url = self._validate_url(urljoin(current_url, location))
                        continue
                    if response.status_code != 200:
                        raise RINEXDownloadError(
                            f"SRGI download failed with HTTP {response.status_code}; obtain a fresh authorized download URL"
                        )
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            advertised_size = int(content_length)
                        except ValueError:
                            advertised_size = None
                        if advertised_size is not None and advertised_size > self.max_bytes:
                            raise RINEXDownloadError(
                                f"SRGI artifact exceeds configured limit of {self.max_bytes} bytes"
                            )
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise RINEXDownloadError(
                                f"SRGI artifact exceeds configured limit of {self.max_bytes} bytes"
                            )
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    if not content:
                        raise RINEXDownloadError("SRGI returned an empty artifact")
                    media_type = response.headers.get("content-type", "").lower()
                    if "text/html" in media_type or self._looks_like_html(content):
                        raise RINEXDownloadError(
                            "SRGI returned HTML instead of a RINEX artifact; login/session or download URL may be required"
                        )
                    name = self._filename(response, current_url)
                    try:
                        return self.cache.store_bytes(
                            content,
                            original_name=name,
                            source_url=self._redacted_source_url(current_url),
                            expected_sha256=expected_sha256,
                            metadata={"provider": "SRGI_BIG", "final_host": self.ALLOWED_HOST},
                        )
                    except RINEXCacheError as exc:
                        raise RINEXDownloadError(str(exc)) from exc
            raise RINEXDownloadError("too many SRGI redirects")
        except httpx.HTTPError as exc:
            raise RINEXDownloadError(f"SRGI request failed: {exc}") from exc
        finally:
            if owns_client:
                client.close()
    @classmethod
    def _validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme.lower() != "https":
            raise RINEXDownloadError("SRGI download URL must use HTTPS")
        if parsed.hostname is None or parsed.hostname.lower() != cls.ALLOWED_HOST:
            raise RINEXDownloadError(f"SRGI download host must be exactly {cls.ALLOWED_HOST}")
        if parsed.username is not None or parsed.password is not None:
            raise RINEXDownloadError("credentials must not be embedded in the SRGI URL")
        if parsed.port not in {None, 443}:
            raise RINEXDownloadError("non-standard SRGI URL port is not allowed")
        if parsed.fragment:
            parsed = parsed._replace(fragment="")
        return urlunparse(parsed)
    @staticmethod
    def _redacted_source_url(value: str) -> str:
        parsed = urlparse(value)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    @staticmethod
    def _looks_like_html(content: bytes) -> bool:
        head = content[:512].lstrip().lower()
        return head.startswith(b"<!doctype html") or head.startswith(b"<html")
    @staticmethod
    def _filename(response: httpx.Response, url: str) -> str:
        content_disposition = response.headers.get("content-disposition", "")
        for token in content_disposition.split(";"):
            key, sep, value = token.strip().partition("=")
            if sep and key.lower() in {"filename", "filename*"}:
                value = value.strip().strip('"')
                if key.lower() == "filename*" and "''" in value:
                    value = value.split("''", 1)[1]
                decoded = unquote(value)
                if decoded:
                    return Path(decoded).name
        name = Path(unquote(urlparse(url).path)).name
        return name or "srgi-rinex.bin"
