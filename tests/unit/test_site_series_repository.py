from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import pytest
from common.errors import NotFoundError
from services.dashboard_service.site_series_repository import SiteSeriesRepository
class _FakeConn:
    def __init__(self, site_row, measurement_rows) -> None:
        self._site_row = site_row
        self._rows = measurement_rows
    async def fetchrow(self, query, *args):
        return self._site_row
    async def fetch(self, query, *args):
        return self._rows
class _FakeAcquireCtx:
    def __init__(self, conn) -> None:
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, *a):
        return False
class _FakePool:
    def __init__(self, site_row, measurement_rows) -> None:
        self._site_row = site_row
        self._rows = measurement_rows
    def acquire(self):
        return _FakeAcquireCtx(_FakeConn(self._site_row, self._rows))
def _row(**kwargs) -> dict:
    return kwargs
def test_groups_points_by_quantity_as_pairs():
    t0 = datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 19, 9, 5, tzinfo=timezone.utc)
    rows = [
        _row(quantity="displacement", unit="mm", time=t0, value=1.0),
        _row(quantity="displacement", unit="mm", time=t1, value=2.0),
        _row(quantity="ppa", unit="g", time=t0, value=0.5),
    ]
    repo = SiteSeriesRepository(_FakePool({"site_id": "lereng-a"}, rows))
    result = asyncio.run(repo.get_series("lereng-a", hours=24))
    by_q = {s["quantity"]: s for s in result["series"]}
    assert set(by_q.keys()) == {"displacement", "ppa"}
    assert by_q["displacement"]["unit"] == "mm"
    assert by_q["displacement"]["points"] == [[t0.isoformat(), 1.0], [t1.isoformat(), 2.0]]
    assert by_q["ppa"]["points"] == [[t0.isoformat(), 0.5]]
def test_unknown_site_raises_not_found():
    repo = SiteSeriesRepository(_FakePool(None, []))
    with pytest.raises(NotFoundError):
        asyncio.run(repo.get_series("does-not-exist", hours=24))
def test_response_always_has_the_four_fields_slopedetail_needs():
    repo = SiteSeriesRepository(_FakePool({"site_id": "lereng-a"}, []))
    result = asyncio.run(repo.get_series("lereng-a", hours=24))
    assert result["sensors"] == []
    assert result["status"] == "unknown"
    assert isinstance(result["action"], str) and result["action"]
    assert isinstance(result["thresholds"], dict) and "displacement" in result["thresholds"]
def test_status_reflects_latest_reading_bahaya_threshold():
    t0 = datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc)
    rows = [_row(quantity="displacement", unit="mm", time=t0, value=111.0)]
    repo = SiteSeriesRepository(_FakePool({"site_id": "SITE-A"}, rows))
    result = asyncio.run(repo.get_series("SITE-A", hours=24))
    assert result["status"] == "bahaya"
    assert result["action"] == "Evacuate - immediate field response."
def test_from_and_to_both_given_uses_between_not_hours():
    from datetime import datetime, timezone
    from common.errors import AppError
    class _RecordingFakeConn(_FakeConn):
        def __init__(self, site_row, rows):
            super().__init__(site_row, rows)
            self.last_query = None
        async def fetch(self, query, *args):
            self.last_query = query
            return self._rows
    class _RecordingFakeAcquireCtx(_FakeAcquireCtx):
        pass
    class _RecordingFakePool(_FakePool):
        def __init__(self, site_row, rows):
            self._site_row = site_row
            self._rows = rows
            self.conn = _RecordingFakeConn(site_row, rows)
        def acquire(self):
            return _RecordingFakeAcquireCtx(self.conn)
    t0 = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)
    rows = [_row(quantity="tilt_x", unit="deg", time=t0, value=1.4)]
    pool = _RecordingFakePool({"site_id": "SITE-ITB-01"}, rows)
    repo = SiteSeriesRepository(pool)
    from_dt = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)
    to_dt = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)
    asyncio.run(repo.get_series("SITE-ITB-01", hours=24, from_time=from_dt, to_time=to_dt))
    assert "BETWEEN" in pool.conn.last_query
def test_only_hours_given_still_uses_make_interval_legacy_behavior():
    from common.errors import AppError
    class _RecordingFakeConn(_FakeConn):
        def __init__(self, site_row, rows):
            super().__init__(site_row, rows)
            self.last_query = None
        async def fetch(self, query, *args):
            self.last_query = query
            return self._rows
    class _RecordingFakePool(_FakePool):
        def __init__(self, site_row, rows):
            self._site_row = site_row
            self._rows = rows
            self.conn = _RecordingFakeConn(site_row, rows)
        def acquire(self):
            return _FakeAcquireCtx(self.conn)
    pool = _RecordingFakePool({"site_id": "SITE-ITB-01"}, [])
    repo = SiteSeriesRepository(pool)
    asyncio.run(repo.get_series("SITE-ITB-01", hours=24))
    assert "make_interval" in pool.conn.last_query
def test_from_after_to_raises_validation_error():
    from datetime import datetime, timezone
    from common.errors import AppError
    t_early = datetime(2026, 9, 18, tzinfo=timezone.utc)
    t_late = datetime(2026, 9, 19, tzinfo=timezone.utc)
    repo = SiteSeriesRepository(_FakePool({"site_id": "SITE-ITB-01"}, []))
    try:
        asyncio.run(repo.get_series("SITE-ITB-01", hours=24, from_time=t_late, to_time=t_early))
        assert False, "harusnya raise AppError"
    except AppError:
        pass
