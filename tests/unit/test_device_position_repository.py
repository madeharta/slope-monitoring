from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from services.monitoring_service.device_position_repository import DevicePositionRepository


class _Conn:
    def __init__(self):
        self.query = None
        self.args = None

    async def execute(self, query, *args):
        self.query = query
        self.args = args


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        return False


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        return _Ctx(self.conn)


def _sample(**overrides):
    values = dict(
        timestamp_utc=datetime(2026, 10, 8, 4, 0, tzinfo=timezone.utc),
        device_id="ROVER-B1-01",
        latitude=-6.8671,
        longitude=107.5787,
        altitude_m=812.4,
        gnss_fix_type=3,
        h_acc_m=0.03,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_write_rtk_direct_persists_gnss_position_as_unvalidated():
    pool = _Pool()
    repo = DevicePositionRepository(pool)
    asyncio.run(repo.write_rtk_direct(site_id="ITB-STAGING-01", sample=_sample()))

    assert "device_position_records" in pool.conn.query
    assert "'rtk_direct', 'unvalidated'" in pool.conn.query
    assert pool.conn.args[1] == "ROVER-B1-01"
    assert pool.conn.args[2] == "ITB-STAGING-01"
    assert pool.conn.args[3] == -6.8671
    assert pool.conn.args[4] == 107.5787


def test_invalid_fix_is_not_written():
    pool = _Pool()
    repo = DevicePositionRepository(pool)
    asyncio.run(repo.write_rtk_direct(site_id="ITB-STAGING-01", sample=_sample(gnss_fix_type=0)))
    assert pool.conn.query is None
