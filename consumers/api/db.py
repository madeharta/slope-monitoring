
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=ROOT_DIR / ".env", override=True)

_pool: asyncpg.Pool | None = None


async def connect() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "magris"),
            user=os.getenv("DB_USER", "magris"),
            password=os.getenv("DB_PASSWORD", "magris_dev"),
            min_size=1,
            max_size=6,
        )
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def sites() -> list[dict]:
    rows = await _pool.fetch("SELECT site_id, name, lat, lon FROM sites ORDER BY site_id")
    return [dict(r) for r in rows]


async def devices() -> list[dict]:
    rows = await _pool.fetch(
        """
        SELECT device_id, device_type, site_id, last_seen,
               (last_seen IS NOT NULL AND now() - last_seen < interval '2 minutes') AS online
        FROM devices ORDER BY device_id
        """
    )
    return [dict(r) for r in rows]


async def quantities() -> list[dict]:
    rows = await _pool.fetch(
        "SELECT DISTINCT quantity, unit FROM measurements ORDER BY quantity"
    )
    return [dict(r) for r in rows]


async def latest_readings() -> list[dict]:
    """Most recent reading per (device, quantity) — the registry-driven basis
    for status and the overview."""
    rows = await _pool.fetch(
        """
        SELECT DISTINCT ON (device_id, quantity)
               device_id, site_id, quantity, value, unit, depth_cm, time
        FROM measurements
        ORDER BY device_id, quantity, time DESC
        """
    )
    return [dict(r) for r in rows]


async def site_latest(site_id: str) -> list[dict]:
    rows = await _pool.fetch(
        """
        SELECT DISTINCT ON (device_id, quantity)
               device_id, quantity, value, unit, depth_cm, time
        FROM measurements
        WHERE site_id = $1
        ORDER BY device_id, quantity, time DESC
        """,
        site_id,
    )
    return [dict(r) for r in rows]


async def series(site_id: str, hours: int = 24, bucket_minutes: int = 10) -> list[dict]:
    """Time-bucketed history per quantity for one slope (Level 2 chart)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await _pool.fetch(
        """
        SELECT time_bucket($1, time) AS t, quantity, unit,
               avg(value) AS value
        FROM measurements
        WHERE site_id = $2 AND time >= $3
        GROUP BY t, quantity, unit
        ORDER BY t
        """,
        timedelta(minutes=bucket_minutes),
        site_id,
        since,
    )
    return [dict(r) for r in rows]


async def data_quality(site_id: str) -> dict:
    row = await _pool.fetchrow(
        """
        SELECT
          count(*) FILTER (WHERE time > now() - interval '1 minute') AS recent,
          count(*) FILTER (WHERE value IS NULL) AS stuck_or_nan,
          count(*) FILTER (WHERE quality_flag <> 'ok') AS flagged
        FROM measurements
        WHERE site_id = $1 AND time > now() - interval '10 minutes'
        """,
        site_id,
    )
    r = dict(row) if row else {}
    return {
        "message_rate": round((r.get("recent") or 0) / 60.0, 2),
        "flagged": r.get("flagged") or 0,
        "stuck": r.get("stuck_or_nan") or 0,
    }
