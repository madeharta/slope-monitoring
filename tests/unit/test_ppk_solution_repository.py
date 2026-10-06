from datetime import datetime, timezone
from types import SimpleNamespace
import asyncio

from ml.pipeline.preprocessing.ppk_engine import PPKSolutionEpoch, PPKWindowResult
from services.monitoring_service.ppk_solution_repository import PPKSolutionRepository


class _Conn:
    def __init__(self):
        self.args = None
        self.query = None

    async def execute(self, query, *args):
        self.query = query
        self.args = args


class _Ctx:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *args): return False


class _Pool:
    def __init__(self): self.conn = _Conn()
    def acquire(self): return _Ctx(self.conn)


def test_write_accepted_persists_schema_quality_and_provenance():
    pool = _Pool()
    repo = PPKSolutionRepository(pool)
    solution = PPKSolutionEpoch(
        timestamp_utc=datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
        latitude=-6.2, longitude=106.8, ellipsoidal_height_m=500.0,
        rtklib_quality=1, satellites=12, sdn_m=0.002, sde_m=0.003, sdu_m=0.004,
        age_s=0.5, ratio=12.0,
    )
    result = PPKWindowResult(
        solutions=(solution,), navigation_sha256="a" * 64,
        navigation_source_url="https://example.test/nav", navigation_provider="BKG_WRD",
        navigation_cache_hit=True, rtklib_config_sha256="b" * 64,
    )
    disp = SimpleNamespace(de_mm=1.0, dn_mm=2.0, du_mm=3.0, total_mm=3.741657)
    asyncio.run(repo.write_accepted(
        site_id="SITE-A", base_device_id="BASE-01", rover_device_id="ROVER-B1-01",
        solution=solution, result=result, displacement=disp,
    ))
    assert "ppk_solution_records" in pool.conn.query
    assert "'accepted', 'unvalidated'" in pool.conn.query
    assert "ppk.solution.v1" in pool.conn.args
    assert "a" * 64 in pool.conn.args
    assert "b" * 64 in pool.conn.args
