"""BC-01: independent, DB-clock-driven, transactional expiry (informational only)."""
from __future__ import annotations
import asyncio
import os
from services.device_config_service.blast_expiry import expired
from services.device_config_service.config_repository import DeviceConfigRepository


async def expire_one_on_conn(conn, base_id: str) -> bool:
    """Caller owns transaction. The trigger row lock serializes with START/RESET/ACK."""
    row = await conn.fetchrow(
        """SELECT config_value, updated_at FROM device_config
           WHERE device_id=$1 AND config_key='TriggerStart' FOR UPDATE""", base_id)
    if row is None or str(row['config_value']).strip().lower() not in ('1', 'true'):
        return False
    timeout = await conn.fetchrow(
        "SELECT config_value FROM device_config WHERE device_id=$1 AND config_key='TimeOutTrigger'", base_id)
    now = await conn.fetchval('SELECT clock_timestamp()')
    if not expired(row['updated_at'], timeout['config_value'] if timeout else None, now):
        return False
    # Audited in the same transaction as config + pending. Rollback on any error.
    await conn.execute(
        """INSERT INTO blast_trigger_timeout_events (device_id, started_at, expired_at, reason)
           VALUES ($1,$2,$3,'TIMEOUT_EXPIRED')
           ON CONFLICT (device_id,started_at) DO NOTHING""", base_id, row['updated_at'], now)
    await DeviceConfigRepository(None).set_site_trigger_on_conn(
        conn, base_id, 0, None, 'TIMEOUT_EXPIRED')
    return True


async def reconcile_once(pool, *, limit: int = 100) -> int:
    if not 1 <= limit <= 1000:
        raise ValueError('limit must be 1..1000')
    async with pool.acquire() as conn:
        candidates = await conn.fetch(
            """SELECT device_id FROM device_config WHERE config_key='TriggerStart'
               AND config_value::text IN ('1','true')
               ORDER BY updated_at, device_id LIMIT $1""", limit)
    total = 0
    for candidate in candidates:
        async with pool.acquire() as conn:
            async with conn.transaction():
                total += bool(await expire_one_on_conn(conn, candidate['device_id']))
    return total


async def _main():
    import asyncpg
    import json
    # Never print credentials or a complete DSN.
    dsn = os.environ.get('BC01_DATABASE_DSN')
    if not dsn:
        raise RuntimeError('BC01_DATABASE_DSN is required (inject as a secret)')
    async def init_conn(conn):
        await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads,
                                  schema='pg_catalog')
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, init=init_conn)
    try:
        while True:
            try:
                await reconcile_once(pool)
            except Exception:
                import logging
                logging.exception('BC01 expiry reconciliation failed; will retry')
            await asyncio.sleep(10)
    finally:
        await pool.close()

if __name__ == '__main__':
    asyncio.run(_main())
