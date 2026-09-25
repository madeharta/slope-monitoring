from __future__ import annotations
from dataclasses import dataclass
_BASE_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
@dataclass(frozen=True)
class WeatherReading:
    latitude: float
    longitude: float
    temperature_c: float
    humidity_pct: float
    rainfall_mm: float
    rainfall_24h_mm: float
    rainfall_72h_mm: float
    fetched_at_iso: str
class OpenMeteoError(RuntimeError):
    pass
async def fetch_current_weather(latitude: float, longitude: float, timeout_s: float = 10.0) -> WeatherReading:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,precipitation",
        "daily": "precipitation_sum",
        "past_days": 3,
        "forecast_days": 1,
        "timezone": "auto",
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
def parse_open_meteo_response(body: dict, latitude: float, longitude: float) -> WeatherReading:
    try:
        current = body["current"]
        daily_sums = [float(v) for v in body["daily"]["precipitation_sum"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenMeteoError(f"unexpected Open-Meteo response shape: {exc}") from exc
    if not daily_sums:
        raise OpenMeteoError("Open-Meteo response had an empty daily.precipitation_sum array")
    rainfall_24h = sum(daily_sums[-1:])
    rainfall_72h = sum(daily_sums[-min(3, len(daily_sums)):])
    try:
        return WeatherReading(
            latitude=latitude,
            longitude=longitude,
            temperature_c=float(current["temperature_2m"]),
            humidity_pct=float(current["relative_humidity_2m"]),
            rainfall_mm=float(current["precipitation"]),
            rainfall_24h_mm=rainfall_24h,
            rainfall_72h_mm=rainfall_72h,
            fetched_at_iso=str(current["time"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenMeteoError(f"unexpected Open-Meteo response shape: {exc}") from exc
