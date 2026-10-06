from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_BASE_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"


@dataclass(frozen=True)
class WeatherReading:
    latitude: float
    longitude: float
    temperature_c: float
    humidity_pct: float
    rainfall_mm: float
    rainfall_24h_mm: float | None
    rainfall_72h_mm: float | None
    fetched_at_iso: str


class OpenMeteoError(RuntimeError):
    pass


async def fetch_current_weather(latitude: float, longitude: float, timeout_s: float = 10.0) -> WeatherReading:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,precipitation",
        "hourly": "precipitation",
        "past_days": 3,
        "forecast_days": 1,
        "timezone": "UTC",
    }
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(_BASE_URL, params=params)
            response.raise_for_status()
            body = response.json()
    except ImportError as exc:
        raise OpenMeteoError(
            "httpx belum terinstal — jalankan 'pip install -r requirements.txt' lalu restart server"
        ) from exc
    except Exception as exc:
        raise OpenMeteoError(f"Open-Meteo request failed: {exc}") from exc

    return parse_open_meteo_response(body, latitude, longitude)


def _parse_hour(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("hourly/current time must be an ISO timestamp string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _rolling_sum_complete_hours(
    times: object,
    values: object,
    *,
    current_time: str,
    window_hours: int,
) -> float | None:
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        return None

    try:
        cutoff = _parse_hour(current_time).replace(minute=0, second=0, microsecond=0)
    except (TypeError, ValueError):
        return None

    buckets: dict[datetime, float] = {}
    for raw_time, raw_value in zip(times, values, strict=True):
        if raw_value is None:
            continue
        try:
            hour = _parse_hour(raw_time)
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        buckets[hour] = value

    expected = [cutoff - timedelta(hours=offset) for offset in range(window_hours, 0, -1)]
    if any(hour not in buckets for hour in expected):
        return None

    return sum(buckets[hour] for hour in expected)


def parse_open_meteo_response(body: dict, latitude: float, longitude: float) -> WeatherReading:
    try:
        current = body["current"]
        current_time = str(current["time"])
        temperature_c = float(current["temperature_2m"])
        humidity_pct = float(current["relative_humidity_2m"])
        rainfall_mm = float(current["precipitation"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenMeteoError(f"unexpected Open-Meteo response shape: {exc}") from exc

    hourly = body.get("hourly")
    hourly_times = hourly.get("time") if isinstance(hourly, dict) else None
    hourly_precip = hourly.get("precipitation") if isinstance(hourly, dict) else None

    rainfall_24h = _rolling_sum_complete_hours(
        hourly_times,
        hourly_precip,
        current_time=current_time,
        window_hours=24,
    )
    rainfall_72h = _rolling_sum_complete_hours(
        hourly_times,
        hourly_precip,
        current_time=current_time,
        window_hours=72,
    )

    return WeatherReading(
        latitude=latitude,
        longitude=longitude,
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        rainfall_mm=rainfall_mm,
        rainfall_24h_mm=rainfall_24h,
        rainfall_72h_mm=rainfall_72h,
        fetched_at_iso=current_time,
    )
