"""Read-only last persisted weather contract; fake asyncpg pool, no network or DB writes."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from apps.api.routers.v1.weather import get_latest_weather


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.query = None

    async def fetch(self, query):
        self.query = query
        return self.rows


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_latest_weather_reads_persisted_snapshot_without_time_window():
    t = datetime(2026, 10, 13, 14, 15, tzinfo=timezone.utc)
    conn = FakeConn([{
        "site_id": "SITE-1", "observed_at": t,
        "rainfall_mm": 0.0, "rainfall_24h_mm": 2.9,
        "rainfall_72h_mm": None, "temperature_c": 30.7,
        "humidity_pct": 39.0,
    }])
    with patch("apps.api.routers.v1.weather.get_db_pool", return_value=FakePool(conn)):
        result = await get_latest_weather(request=object(), user=object())
    assert result["sites"]["SITE-1"]["rainfall_mm"] == 0.0
    assert result["sites"]["SITE-1"]["observed_at"] == t.isoformat()
    assert "MAX(time)" in conn.query
    assert "now()" not in conn.query.lower()
    assert "source_kind = 'external'" in conn.query


@pytest.mark.asyncio
async def test_latest_weather_empty_database():
    with patch("apps.api.routers.v1.weather.get_db_pool", return_value=FakePool(FakeConn([]))):
        result = await get_latest_weather(request=object(), user=object())
    assert result == {"ok": True, "sites": {}}
