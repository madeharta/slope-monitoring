"""PostgreSQL-only BC-01 acceptance. Uses a fresh schema and drops it afterwards."""
import asyncio
import json
import os
import uuid
from datetime import timedelta
import pytest

async def acceptance():
    import asyncpg
    from services.device_config_service.blast_timeout_reconciler import reconcile_once
    from services.device_config_service.trigger_ack_service import acknowledge_trigger_start
    dsn = os.getenv('BC01_TEST_DATABASE_DSN')
    if not dsn:
        pytest.skip('BC01_TEST_DATABASE_DSN not supplied; no DB acceptance asserted')
    schema = 'bc01_test_' + uuid.uuid4().hex[:16]
    admin = await asyncpg.connect(dsn)
    pool = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'''CREATE TABLE "{schema}".devices(device_id text primary key)''')
        await admin.execute(f'''INSERT INTO "{schema}".devices VALUES ('BASE-01')''')
        await admin.execute(f'''CREATE TABLE "{schema}".device_config(
          device_id text, config_key text, config_value jsonb, updated_by text,
          updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(device_id,config_key))''')
        await admin.execute(f'''CREATE TABLE "{schema}".device_config_pending(
          id bigserial primary key, device_id text, config_key text,
          config_value jsonb, created_at timestamptz default now(), acked_at timestamptz)''')
        await admin.execute(f'''CREATE TABLE "{schema}".blast_trigger_timeout_events(
          id bigserial primary key, device_id text, started_at timestamptz,
          expired_at timestamptz, reason text, UNIQUE(device_id,started_at))''')
        async def init_conn(conn):
            await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')
        await admin.execute(f'''CREATE TABLE "{schema}".blast_trigger_acks(
          id bigserial primary key, device_id text, pending_config_id bigint, trigger_start int,
          received bool, device_timestamp_utc timestamptz, server_received_at timestamptz,
          device_role text, iccid text, device_version text)''')
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4,
            init=init_conn, server_settings={'search_path': schema})
        async with pool.acquire() as c:
            await c.execute("""INSERT INTO device_config(device_id,config_key,config_value,updated_by)
              VALUES ('BASE-01','TriggerStart','1','tester'),('BASE-01','TimeOutTrigger','1','tester')""")
            # Simulate the elapsed 61 seconds without making an HTTP request.
            await c.execute("""UPDATE device_config SET updated_at=clock_timestamp()-interval '61 seconds'
              WHERE config_key='TriggerStart'""")
        assert await reconcile_once(pool) == 1, 'expired START was not reset'
        assert await reconcile_once(pool) == 0, 'retry reset twice'
        assert not await acknowledge_trigger_start(pool, device_id='BASE-01', trigger_start=1), 'late START ACK accepted'
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT config_value::text FROM device_config WHERE config_key='TriggerStart'") == '0'
            assert await c.fetchval("SELECT count(*) FROM blast_trigger_timeout_events") == 1
            assert await c.fetchval("SELECT count(*) FROM device_config_pending WHERE config_key='TriggerStart'") == 1
            # New generation: stale previous deadline must not reset current START.
            await c.execute("""UPDATE device_config SET config_value='1',updated_at=clock_timestamp()
              WHERE config_key='TriggerStart'""")
        assert await reconcile_once(pool) == 0, 'new START was reset prematurely'
        # Concurrency: two workers cannot insert duplicate reset/pending/audit.
        async with pool.acquire() as c:
            await c.execute("""UPDATE device_config SET updated_at=clock_timestamp()-interval '61 seconds'
              WHERE config_key='TriggerStart'""")
        results = await asyncio.gather(reconcile_once(pool), reconcile_once(pool))
        assert sum(results) == 1, results
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT count(*) FROM blast_trigger_timeout_events") == 2
            assert await c.fetchval("SELECT count(*) FROM device_config_pending WHERE config_key='TriggerStart'") == 2
        # Failure to write audit must roll back reset and pending update.
        async with pool.acquire() as c:
            await c.execute("UPDATE device_config SET config_value='1',updated_at=clock_timestamp()-interval '61 seconds' WHERE config_key='TriggerStart'")
            await c.execute("""ALTER TABLE device_config_pending ADD CONSTRAINT reject_zero_test
                CHECK (NOT (config_key='TriggerStart' AND config_value='0'::jsonb)) NOT VALID""")
        with pytest.raises(asyncpg.CheckViolationError):
            await reconcile_once(pool)
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT config_value::text FROM device_config WHERE config_key='TriggerStart'") == '1'
            assert await c.fetchval("SELECT count(*) FROM device_config_pending WHERE config_key='TriggerStart'") == 2
            assert await c.fetchval("SELECT count(*) FROM blast_trigger_timeout_events") == 2
    finally:
        if pool: await pool.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


def test_bc01_postgres_acceptance():
    asyncio.run(acceptance())
