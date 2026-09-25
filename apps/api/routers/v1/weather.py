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
DEFAULT_POLL_INTERVAL_S = 15 * 60
async def _fetch_and_write_one_site(pool, site_id: str, lat: float, lon: float) -> WeatherReading:
    reading = await fetch_current_weather(lat, lon)
    await MeasurementsWriter(pool).write_weather(
        site_id=site_id, timestamp_utc=datetime.now(timezone.utc),
        rainfall_mm=reading.rainfall_mm, temperature_c=reading.temperature_c, humidity_pct=reading.humidity_pct,
        rainfall_24h_mm=reading.rainfall_24h_mm, rainfall_72h_mm=reading.rainfall_72h_mm,
    )
    return reading
async def fetch_and_store_all_sites(pool) -> None:
    async with pool.acquire() as conn:
        sites = await conn.fetch("SELECT site_id, lat, lon FROM sites")
    for row in sites:
        try:
            await _fetch_and_write_one_site(pool, row["site_id"], row["lat"], row["lon"])
        except OpenMeteoError as exc:
            logger.warning("weather fetch failed for site %s: %s", row["site_id"], exc)
async def weather_poll_loop(pool, interval_s: float = DEFAULT_POLL_INTERVAL_S) -> None:
    while True:
        try:
            await fetch_and_store_all_sites(pool)
        except Exception:
            logger.exception("weather_poll_loop: unexpected error in a poll cycle, continuing")
        await asyncio.sleep(interval_s)
@router.post("/fetch/{site_id}")
async def fetch_weather(
    site_id: str, request: Request, user: TokenPayload = Depends(require_role("operator")),
) -> dict:
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
