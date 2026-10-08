"""POST /api/v1/weather/fetch/{site_id} — fetches current weather from
Open-Meteo (services/weather_service/open_meteo_client.py) for a site's
coordinates and writes it into `measurements` as *_external quantities.

Live mechanism (2026-09-19, added): rather than requiring an external
cron, a background asyncio task (see apps/api/main.py lifespan) calls
`fetch_and_store_all_sites()` below on a fixed interval for as long as the
API process is running — no separate scheduler service needed for this
POC's scale. A true production deployment with many sites may eventually
want a real task queue instead; noted, not built, since the in-process
loop is sufficient at current scale and adds zero extra infrastructure.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from apps.api.dependencies import get_db_pool, require_role
from common.errors import AppError, ErrorCode
from common.security import TokenPayload
from services.monitoring_service.measurements_writer import MeasurementsWriter
from services.weather_service.open_meteo_client import WeatherReading, OpenMeteoError, fetch_current_weather
from services.weather_service.site_repository import SiteRepository

logger = logging.getLogger("slope_monitoring.weather")

router = APIRouter(prefix="/api/v1/weather", tags=["weather"])

DEFAULT_POLL_INTERVAL_S = 15 * 60  # 15 minutes — reasonable for slow-changing rainfall accumulation, well under Open-Meteo's free-tier daily call budget even with many sites


async def _fetch_and_write_one_site(pool, site_id: str, lat: float, lon: float) -> WeatherReading:
    reading = await fetch_current_weather(lat, lon)
    observed_at = datetime.fromisoformat(reading.fetched_at_iso.replace("Z", "+00:00"))
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    await MeasurementsWriter(pool).write_weather(
        site_id=site_id, timestamp_utc=observed_at.astimezone(timezone.utc),
        rainfall_mm=reading.rainfall_mm, temperature_c=reading.temperature_c, humidity_pct=reading.humidity_pct,
        rainfall_24h_mm=reading.rainfall_24h_mm, rainfall_72h_mm=reading.rainfall_72h_mm,
    )
    return reading


async def fetch_and_store_all_sites(pool) -> None:
    """Called by the background loop (main.py lifespan) AND reusable
    on-demand. Iterates every site, fetching+writing weather for each —
    one site's failure is logged and skipped, never aborts the rest (a
    single flaky API call must not silently stop weather updates for
    every other site)."""
    async with pool.acquire() as conn:
        sites = await conn.fetch("SELECT site_id, lat, lon FROM sites")
    for row in sites:
        try:
            await _fetch_and_write_one_site(pool, row["site_id"], row["lat"], row["lon"])
        except OpenMeteoError as exc:
            logger.warning("weather fetch failed for site %s: %s", row["site_id"], exc)


async def weather_poll_loop(pool, interval_s: float = DEFAULT_POLL_INTERVAL_S) -> None:
    """Runs forever (until cancelled at app shutdown) — started as an
    asyncio background task in main.py's lifespan, not awaited directly."""
    while True:
        try:
            await fetch_and_store_all_sites(pool)
        except Exception:  # noqa: BLE001 — a background loop must never die from one bad cycle
            logger.exception("weather_poll_loop: unexpected error in a poll cycle, continuing")
        await asyncio.sleep(interval_s)


@router.post("/fetch/{site_id}")
async def fetch_weather(
    site_id: str, request: Request, user: TokenPayload = Depends(require_role("operator")),
) -> dict:
    """On-demand single-site fetch — same underlying logic as the
    background loop, exposed for manual testing/refresh-now use."""
    pool = get_db_pool(request)
    lat, lon = await SiteRepository(pool).get_coordinates(site_id)

    try:
        reading = await _fetch_and_write_one_site(pool, site_id, lat, lon)
    except OpenMeteoError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"weather fetch failed: {exc}") from exc

    return {
        "ok": True, "site_id": site_id,
        "reading": {
            "rainfall_mm": reading.rainfall_mm, "rainfall_24h_mm": reading.rainfall_24h_mm,
            "rainfall_72h_mm": reading.rainfall_72h_mm, "temperature_c": reading.temperature_c,
            "humidity_pct": reading.humidity_pct, "observed_at": reading.fetched_at_iso,
        },
    }
