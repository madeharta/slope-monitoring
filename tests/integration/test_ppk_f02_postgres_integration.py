"""PPK F-02 integration acceptance; isolated schema, real migrations 022 + 025."""
import asyncio
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from ml.pipeline.preprocessing.ppk_engine import PPKSolutionEpoch, PPKWindowResult
from services.monitoring_service.ppk_solution_repository import PPKSolutionRepository, PPKSolutionConflictError

MIGRATION_022 = Path('data/db/migrations/022_ppk_solution_records.sql')
MIGRATION_025 = Path('data/db/migrations/025_ppk_solution_provenance.sql')


def case_args(*, de=1.0, nav_hash='a'):
    sol = PPKSolutionEpoch(
        timestamp_utc=datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
        latitude=-6.2, longitude=106.8, ellipsoidal_height_m=500.0,
        rtklib_quality=1, satellites=12, sdn_m=.002, sde_m=.003, sdu_m=.004,
        age_s=.5, ratio=12.0,
    )
    hashes = dict(
        base_rawx_sha256='c'*64, rover_rawx_sha256='d'*64,
        base_obs_sha256='e'*64, rover_obs_sha256='f'*64,
        normalized_navigation_sha256='1'*64, convbin_sha256='2'*64,
        rnx2rtkp_sha256='3'*64, solution_pos_sha256='4'*64,
    )
    result = PPKWindowResult(
        solutions=(sol,), navigation_sha256=nav_hash*64,
        navigation_source_url=None, navigation_provider=None,
        navigation_cache_hit=True, rtklib_config_sha256='b'*64, **hashes,
    )
    return dict(
        site_id='SITE-A', base_device_id='BASE-01', rover_device_id='ROVER-B1-01',
        solution=sol, result=result,
        displacement=SimpleNamespace(de_mm=de, dn_mm=2.0, du_mm=3.0, total_mm=3.74),
    )


async def acceptance(dsn):
    import asyncpg
    schema = 'ppk_f02_' + uuid.uuid4().hex[:16]
    admin = await asyncpg.connect(dsn)
    pool = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'CREATE TABLE "{schema}".sites (site_id TEXT PRIMARY KEY)')
        await admin.execute(f'CREATE TABLE "{schema}".devices (device_id TEXT PRIMARY KEY)')
        await admin.execute(f"INSERT INTO \"{schema}\".sites VALUES ('SITE-A')")
        await admin.execute(f"INSERT INTO \"{schema}\".devices VALUES ('BASE-01'),('ROVER-B1-01')")
        # Exact migrations, scoped by search_path; no public schema modifications.
        await admin.execute(f'SET search_path TO "{schema}"')
        await admin.execute(MIGRATION_022.read_text())
        await admin.execute(MIGRATION_025.read_text())
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4,
            server_settings={'search_path': schema})
        repo = PPKSolutionRepository(pool)
        good = case_args()
        await repo.write_accepted(**good)
        async with pool.acquire() as c:
            before = await c.fetchrow('SELECT *, xmin::text AS row_version FROM ppk_solution_records')
            assert before['validation_status'] == 'unvalidated'
            assert before['quality_gate_status'] == 'accepted'
        await repo.write_accepted(**good)
        async with pool.acquire() as c:
            after = await c.fetchrow('SELECT *, xmin::text AS row_version FROM ppk_solution_records')
        assert dict(after) == dict(before), 'identical retry must not touch row or processed_at'
        with pytest.raises(PPKSolutionConflictError):
            await repo.write_accepted(**case_args(de=9.0))
        with pytest.raises(PPKSolutionConflictError):
            await repo.write_accepted(**case_args(nav_hash='9'))
        async with pool.acquire() as c:
            assert dict(await c.fetchrow('SELECT *, xmin::text AS row_version FROM ppk_solution_records')) == dict(before)
        # Identical concurrency with distinct connections.
        await asyncio.gather(repo.write_accepted(**good), repo.write_accepted(**good))
        async with pool.acquire() as c:
            assert await c.fetchval('SELECT count(*) FROM ppk_solution_records') == 1
        # Conflicting concurrent attempts on another epoch; exactly one may win.
        newer = case_args()
        newer['solution'] = PPKSolutionEpoch(**{**newer['solution'].__dict__, 'timestamp_utc': datetime(2026, 9, 26, 13, tzinfo=timezone.utc)})
        rival = dict(newer, displacement=SimpleNamespace(de_mm=99.0, dn_mm=2.0, du_mm=3.0, total_mm=3.74))
        outcomes = await asyncio.gather(repo.write_accepted(**newer), repo.write_accepted(**rival), return_exceptions=True)
        assert sum(isinstance(x, PPKSolutionConflictError) for x in outcomes) == 1, outcomes
        assert sum(x is None for x in outcomes) == 1, outcomes
        async with pool.acquire() as c:
            assert await c.fetchval('SELECT count(*) FROM ppk_solution_records') == 2
            saved = await c.fetchval('SELECT displacement_e_mm FROM ppk_solution_records WHERE time=$1', newer['solution'].timestamp_utc)
            assert saved in (1.0, 99.0)
        print('PPK_F02_POSTGRES_INTEGRATION_PASS: insert, retry, changed fields, provenance, concurrency')
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


def test_ppk_f02_postgres():
    dsn = os.environ.get('PPK_F02_TEST_DATABASE_DSN')
    if not dsn:
        pytest.skip('PPK_F02_TEST_DATABASE_DSN not configured')
    asyncio.run(acceptance(dsn))
