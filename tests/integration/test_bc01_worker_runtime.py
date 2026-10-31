"""End-to-end BC-01 daemon smoke: isolated PostgreSQL schema, no HTTP requests."""
import asyncio
import json
import os
import sys
import uuid
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode

import pytest


def with_search_path(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if 'options' in query:
        raise ValueError('Test DSN must not already contain options')
    query['options'] = '-csearch_path=' + schema
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def run_smoke():
    asyncpg = pytest.importorskip('asyncpg')
    dsn = os.environ.get('BC01_TEST_DATABASE_DSN')
    if not dsn:
        pytest.skip('BC01_TEST_DATABASE_DSN required')
    if '127.0.0.1' not in (urlsplit(dsn).hostname or '', 'localhost'):
        raise ValueError('Refusing a non-local database for runtime smoke')
    schema = 'bc01_runtime_' + uuid.uuid4().hex[:16]
    admin = await asyncpg.connect(dsn)
    proc = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'CREATE TABLE "{schema}".devices (device_id text primary key)')
        await admin.execute(f"INSERT INTO \"{schema}\".devices VALUES ('BASE-01')")
        await admin.execute(f'''CREATE TABLE "{schema}".device_config (
            device_id text, config_key text, config_value jsonb,
            updated_by text, updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(device_id, config_key))''')
        await admin.execute(f'''CREATE TABLE "{schema}".device_config_pending (
            id bigserial primary key, device_id text, config_key text,
            config_value jsonb, created_at timestamptz DEFAULT now(), acked_at timestamptz)''')
        await admin.execute(f'''CREATE TABLE "{schema}".blast_trigger_timeout_events (
            id bigserial primary key, device_id text, started_at timestamptz,
            expired_at timestamptz, reason text,
            UNIQUE(device_id, started_at))''')
        scoped = with_search_path(dsn, schema)
        db = await asyncpg.connect(scoped)
        try:
            await db.execute('''INSERT INTO device_config(device_id,config_key,config_value,updated_by)
                VALUES ('BASE-01','TriggerStart','1','smoke'),
                       ('BASE-01','TimeOutTrigger','1','smoke')''')
            await db.execute("UPDATE device_config SET updated_at=clock_timestamp()-interval '61 seconds' WHERE config_key='TriggerStart'")
            env = os.environ.copy()
            env['BC01_DATABASE_DSN'] = scoped
            proc = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'services.device_config_service.blast_timeout_reconciler',
                env=env, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE)
            ok = False
            for _ in range(60):
                if proc.returncode is not None:
                    err = (await proc.stderr.read()).decode(errors='replace')[-2000:]
                    pytest.fail('Worker exited before reset: ' + err.replace(scoped, '[REDACTED]'))
                state = await db.fetchval("SELECT config_value::text FROM device_config WHERE config_key='TriggerStart'")
                audit = await db.fetchval('SELECT COUNT(*) FROM blast_trigger_timeout_events')
                pending = await db.fetchval("SELECT COUNT(*) FROM device_config_pending WHERE config_key='TriggerStart'")
                if state == '0' and audit == 1 and pending == 1:
                    ok = True
                    break
                await asyncio.sleep(0.1)
            assert ok, 'Daemon failed to reset DB + write exactly one audit/pending within 6 seconds'
        finally:
            await db.close()
    finally:
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        try:
            await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            await admin.close()


def test_worker_process_without_http():
    asyncio.run(run_smoke())
