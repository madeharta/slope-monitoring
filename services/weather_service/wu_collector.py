"""Standalone opt-in 15-minute collector, NOT started from the FastAPI lifespan.
Usage: python -m services.weather_service.wu_collector
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
import asyncpg
from services.weather_service.wu_client import fetch_current, WUError

log = logging.getLogger('magris.wu')
LOCK_KEY = 151510103

async def save_one(conn, entry):
    return await conn.fetchval('''
        INSERT INTO public.wu_weather_observations(station_id,observed_at,lat,lon,qc_status,payload)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb)
        ON CONFLICT (station_id,observed_at) DO NOTHING RETURNING id
    ''', entry['station_id'],entry['observed_at'],entry['lat'],entry['lon'],entry['qc_status'],json.dumps(entry['values']))

async def run():
    key = os.environ.get('WU_API_KEY','')
    station = os.environ.get('WU_STATION_ID', '').strip()
    if not station:
        raise RuntimeError('WU_STATION_ID missing')
    if not key: raise RuntimeError('WU_API_KEY missing (never put it in Git)')
    conn = await asyncpg.connect(host=os.getenv('DB_HOST','localhost'),port=int(os.getenv('DB_PORT','5432')),
                                 database=os.getenv('DB_NAME','slope'),user=os.getenv('DB_USER','slope'),
                                 password=os.environ['DB_PASSWORD'])
    try:
        acquired=await conn.fetchval('SELECT pg_try_advisory_lock($1)',LOCK_KEY)
        if not acquired:
            log.warning('Collector already running; exiting to avoid duplicate schedules')
            return
        while True:
            try:
                result = await fetch_current(station,key)
                rec = await save_one(conn,result)
                log.info('station=%s observed_at=%s saved=%s qc=%s',station,result['observed_at'].isoformat(),bool(rec),result['qc_status'])
            except (WUError,asyncpg.PostgresError) as exc:
                # No remote request URLs or secrets logged.
                log.warning('poll failed (%s)',type(exc).__name__)
                if conn.is_closed(): raise
            interval = int(os.getenv('WU_POLL_INTERVAL_SECONDS', '900'))
            if interval <= 0:
                raise RuntimeError('WU_POLL_INTERVAL_SECONDS must be positive')
            now = datetime.now(timezone.utc)
            seconds = interval - (now.timestamp() % interval)
            await asyncio.sleep(seconds)
    finally:
        await conn.close()

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    # HTTPX logs complete request URLs, including query-string credentials.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    asyncio.run(run())
