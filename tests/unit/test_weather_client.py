import pytest
from services.weather_service.open_meteo_client import OpenMeteoError, parse_open_meteo_response
_SAMPLE_RESPONSE = {
    "latitude": -6.2,
    "longitude": 106.8,
    "current": {
        "time": "2026-09-19T09:00",
        "temperature_2m": 27.3,
        "relative_humidity_2m": 84.0,
        "precipitation": 2.4,
    },
    "daily": {
        "time": ["2026-09-17", "2026-09-18", "2026-09-19"],
        "precipitation_sum": [5.0, 12.5, 8.2],
    },
}
def test_parses_valid_response():
    reading = parse_open_meteo_response(_SAMPLE_RESPONSE, latitude=-6.2, longitude=106.8)
    assert reading.temperature_c == 27.3
    assert reading.humidity_pct == 84.0
    assert reading.rainfall_mm == 2.4
    assert reading.fetched_at_iso == "2026-09-19T09:00"
    assert reading.latitude == -6.2 and reading.longitude == 106.8
def test_rainfall_24h_is_most_recent_day_only():
    reading = parse_open_meteo_response(_SAMPLE_RESPONSE, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm == 8.2
def test_rainfall_72h_sums_all_three_days():
    reading = parse_open_meteo_response(_SAMPLE_RESPONSE, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_72h_mm == pytest.approx(5.0 + 12.5 + 8.2)
def test_fewer_than_three_days_available_still_works():
    partial = {"current": _SAMPLE_RESPONSE["current"], "daily": {"precipitation_sum": [3.3]}}
    reading = parse_open_meteo_response(partial, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm == 3.3
    assert reading.rainfall_72h_mm == 3.3
def test_empty_daily_array_raises():
    broken = {"current": _SAMPLE_RESPONSE["current"], "daily": {"precipitation_sum": []}}
    with pytest.raises(OpenMeteoError):
        parse_open_meteo_response(broken, latitude=-6.2, longitude=106.8)
def test_missing_current_key_raises_openmeteoerror():
    with pytest.raises(OpenMeteoError):
        parse_open_meteo_response({"latitude": 0, "longitude": 0}, latitude=0, longitude=0)
def test_missing_field_inside_current_raises():
    broken = {"current": {"time": "2026-09-19T09:00", "temperature_2m": 27.3}, "daily": _SAMPLE_RESPONSE["daily"]}
    with pytest.raises(OpenMeteoError):
        parse_open_meteo_response(broken, latitude=0, longitude=0)
def test_non_numeric_field_raises():
    broken = {
        "current": {
            "time": "2026-09-19T09:00",
            "temperature_2m": "not-a-number",
            "relative_humidity_2m": 84.0,
            "precipitation": 2.4,
        },
        "daily": _SAMPLE_RESPONSE["daily"],
    }
    with pytest.raises(OpenMeteoError):
        parse_open_meteo_response(broken, latitude=0, longitude=0)
