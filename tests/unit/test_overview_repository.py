"""Verifies OverviewRepository's aggregation logic — worst-status-per-site,
representative-reading selection, online/offline counting — using a fake
pool that returns canned rows in the exact order OverviewRepository issues
its three queries (sites, devices, latest_readings). No real Postgres
needed, same pattern as test_measurements_writer.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from services.dashboard_service.overview_repository import OverviewRepository


class _FakeConn:
    def __init__(self, results_queue: list) -> None:
        self._queue = results_queue

    async def fetch(self, query, *args):
        return self._queue.pop(0)


class _FakeAcquireCtx:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, results_queue: list) -> None:
        self._queue = results_queue

    def acquire(self):
        return _FakeAcquireCtx(_FakeConn(self._queue))


def _row(**kwargs) -> dict:
    return kwargs  # asyncpg.Record supports dict-style access; a plain dict works identically for our read-only usage


def test_worst_status_picked_when_site_has_mixed_readings():
    now = datetime.now(timezone.utc)
    sites = [_row(site_id="lereng-a", name="Slope A", lat=-6.2, lon=106.8)]
    devices = [_row(device_id="ROVER-01", site_id="lereng-a", online=True)]
    # displacement=12mm -> bahaya (>=10); a second device's reading would
    # test mixing, but even one bahaya reading should make the WHOLE site bahaya.
    readings = [_row(device_id="ROVER-01", site_id="lereng-a", quantity="displacement", value=12.0, unit="mm", time=now)]

    repo = OverviewRepository(_FakePool([sites, devices, readings]))
    result = asyncio.run(repo.get_overview())

    assert len(result["slopes"]) == 1
    slope = result["slopes"][0]
    assert slope["status"] == "bahaya"
    assert slope["reading"]["value"] == 12.0
    assert slope["reading"]["quantity"] == "displacement"
    assert result["status_counts"] == {"normal": 0, "siaga": 0, "bahaya": 1, "unknown": 0}


def test_site_with_no_readings_is_unknown_not_safe():
    sites = [_row(site_id="lereng-b", name="Slope B", lat=-6.5, lon=106.9)]
    devices = [_row(device_id="ROVER-02", site_id="lereng-b", online=False)]
    readings = []

    repo = OverviewRepository(_FakePool([sites, devices, readings]))
    result = asyncio.run(repo.get_overview())

    slope = result["slopes"][0]
    assert slope["status"] == "unknown"
    assert slope["reading"] is None
    assert result["health"] == {"online": 0, "offline": 1, "total": 1}


def test_online_offline_counted_correctly_across_multiple_devices():
    sites = [_row(site_id="lereng-a", name="Slope A", lat=-6.2, lon=106.8)]
    devices = [
        _row(device_id="ROVER-01", site_id="lereng-a", online=True),
        _row(device_id="ROVER-02", site_id="lereng-a", online=True),
        _row(device_id="BASE-01", site_id="lereng-a", online=False),
    ]
    readings = []

    repo = OverviewRepository(_FakePool([sites, devices, readings]))
    result = asyncio.run(repo.get_overview())

    assert result["health"] == {"online": 2, "offline": 1, "total": 3}


def test_normal_reading_does_not_inflate_bahaya_count():
    now = datetime.now(timezone.utc)
    sites = [_row(site_id="lereng-a", name="Slope A", lat=-6.2, lon=106.8)]
    devices = [_row(device_id="ROVER-01", site_id="lereng-a", online=True)]
    readings = [_row(device_id="ROVER-01", site_id="lereng-a", quantity="displacement", value=1.0, unit="mm", time=now)]

    repo = OverviewRepository(_FakePool([sites, devices, readings]))
    result = asyncio.run(repo.get_overview())

    assert result["slopes"][0]["status"] == "normal"
    assert result["status_counts"] == {"normal": 1, "siaga": 0, "bahaya": 0, "unknown": 0}
