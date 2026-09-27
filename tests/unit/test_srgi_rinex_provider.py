from __future__ import annotations
from pathlib import Path
import httpx
import pytest
from services.rinex_service.cache import RINEXCache
from services.rinex_service.srgi_provider import RINEXDownloadError, SRGIRINEXProvider
def _provider(tmp_path: Path, handler):
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, follow_redirects=False)
    return SRGIRINEXProvider(RINEXCache(tmp_path), client=client), client
@pytest.mark.parametrize(
    "url",
    [
        "http://srgi.big.go.id/download/nav.rnx",
        "https://evil.example/nav.rnx",
        "https://srgi.big.go.id.evil.example/nav.rnx",
        "https://user:pass@srgi.big.go.id/nav.rnx",
        "https://srgi.big.go.id:8443/nav.rnx",
    ],
)
def test_provider_rejects_unsafe_urls(tmp_path: Path, url: str):
    provider, client = _provider(tmp_path, lambda request: httpx.Response(500))
    try:
        with pytest.raises(RINEXDownloadError):
            provider.fetch(url)
    finally:
        client.close()
def test_provider_downloads_and_redacts_query(tmp_path: Path):
    payload = b"     3.03           NAVIGATION DATA     M                   RINEX VERSION / TYPE\n"
    def handler(request: httpx.Request):
        assert request.url.host == "srgi.big.go.id"
        return httpx.Response(
            200,
            content=payload,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment; filename="BRDC00IGS_R_20262700000_01D_MN.rnx"',
            },
        )
    provider, client = _provider(tmp_path, handler)
    try:
        artifact = provider.fetch("https://srgi.big.go.id/download/file?token=secret")
    finally:
        client.close()
    assert artifact.path.read_bytes() == payload
    assert artifact.original_name == "BRDC00IGS_R_20262700000_01D_MN.rnx"
    assert artifact.source_url == "https://srgi.big.go.id/download/file"
    assert "token" not in artifact.manifest_path.read_text(encoding="utf-8")
def test_provider_blocks_cross_host_redirect(tmp_path: Path):
    def handler(request: httpx.Request):
        return httpx.Response(302, headers={"Location": "https://evil.example/nav.rnx"})
    provider, client = _provider(tmp_path, handler)
    try:
        with pytest.raises(RINEXDownloadError, match="host"):
            provider.fetch("https://srgi.big.go.id/download/nav")
    finally:
        client.close()
def test_provider_rejects_login_html(tmp_path: Path):
    provider, client = _provider(
        tmp_path,
        lambda request: httpx.Response(200, content=b"<!doctype html><html>login</html>", headers={"Content-Type": "text/html"}),
    )
    try:
        with pytest.raises(RINEXDownloadError, match="HTML"):
            provider.fetch("https://srgi.big.go.id/download/nav")
    finally:
        client.close()
def test_provider_enforces_download_size_limit(tmp_path: Path):
    provider, client = _provider(tmp_path, lambda request: httpx.Response(200, content=b"12345"))
    provider.max_bytes = 4
    try:
        with pytest.raises(RINEXDownloadError, match="limit"):
            provider.fetch("https://srgi.big.go.id/download/nav")
    finally:
        client.close()
