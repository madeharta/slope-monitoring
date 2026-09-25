from __future__ import annotations
import asyncio
import pytest
from services.site_service.site_repository import (
    DuplicateSiteWarning,
    NewSite,
    SiteRepository,
    haversine_distance_m,
)
class _FakeConn:
    def __init__(self, sites: list, sink: list) -> None:
        self._sites = sites
        self._sink = sink
    async def fetch(self, query, *args):
        return self._sites
    async def execute(self, query, *args):
        self._sink.append(args)
class _FakeAcquireCtx:
    def __init__(self, conn) -> None:
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, *a):
        return False
class _FakePool:
    def __init__(self, sites: list, sink: list) -> None:
        self._sites = sites
        self._sink = sink
    def acquire(self):
        return _FakeAcquireCtx(_FakeConn(self._sites, self._sink))
def test_haversine_known_distance_jakarta_bandung():
    d = haversine_distance_m(-6.2088, 106.8456, -6.9175, 107.6191)
    assert 110_000 < d < 130_000
def test_create_far_from_existing_sites_succeeds():
    existing = [{"site_id": "SITE-A", "name": "Lereng Uji A", "lat": -6.2, "lon": 106.8}]
    sink: list = []
    repo = SiteRepository(_FakePool(existing, sink))
    new_site = NewSite(site_id="SITE-B", name="Lereng B", lat=-7.5, lon=110.0)
    asyncio.run(repo.create(new_site))
    assert len(sink) == 1
def test_create_near_existing_site_raises_warning_without_force():
    existing = [{"site_id": "SITE-A", "name": "Lereng Uji A", "lat": -6.2, "lon": 106.8}]
    sink: list = []
    repo = SiteRepository(_FakePool(existing, sink))
    new_site = NewSite(site_id="SITE-A2", name="Lereng A Duplikat?", lat=-6.2001, lon=106.8001)
    with pytest.raises(DuplicateSiteWarning):
        asyncio.run(repo.create(new_site))
    assert len(sink) == 0
def test_create_near_existing_site_succeeds_with_force():
    existing = [{"site_id": "SITE-A", "name": "Lereng Uji A", "lat": -6.2, "lon": 106.8}]
    sink: list = []
    repo = SiteRepository(_FakePool(existing, sink))
    new_site = NewSite(site_id="SITE-A2", name="Lereng A Duplikat?", lat=-6.2001, lon=106.8001)
    asyncio.run(repo.create(new_site, force=True))
    assert len(sink) == 1
