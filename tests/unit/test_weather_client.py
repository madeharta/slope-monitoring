from datetime import datetime, timedelta

import pytest

from services.weather_service.open_meteo_client import OpenMeteoError, parse_open_meteo_response


def _hourly_fixture(hours: int = 80, *, current_time: str = "2026-09-19T09:00") -> dict:
    cutoff = datetime.fromisoformat(current_time)
    start = cutoff - timedelta(hours=hours)
    times = [(start + timedelta(hours=i)).isoformat(timespec="minutes") for i in range(hours)]
    return {
        "latitude": -6.2,
        "longitude": 106.8,
        "current": {
            "time": current_time,
            "temperature_2m": 27.3,
            "relative_humidity_2m": 84.0,
            "precipitation": 2.4,
        },
        "hourly": {
            "time": times,
            "precipitation": [1.0] * hours,
        },
    }


def test_parses_valid_response():
    reading = parse_open_meteo_response(_hourly_fixture(), latitude=-6.2, longitude=106.8)
    assert reading.temperature_c == 27.3
    assert reading.humidity_pct == 84.0
    assert reading.rainfall_mm == 2.4
    assert reading.fetched_at_iso == "2026-09-19T09:00"
    assert reading.latitude == -6.2 and reading.longitude == 106.8


def test_rainfall_24h_uses_last_24_complete_hourly_buckets():
    body = _hourly_fixture()
    body["hourly"]["precipitation"] = [float(i) for i in range(80)]
    reading = parse_open_meteo_response(body, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm == pytest.approx(sum(float(i) for i in range(56, 80)))


def test_rainfall_72h_uses_last_72_complete_hourly_buckets():
    body = _hourly_fixture()
    body["hourly"]["precipitation"] = [float(i) for i in range(80)]
    reading = parse_open_meteo_response(body, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_72h_mm == pytest.approx(sum(float(i) for i in range(8, 80)))


def test_incomplete_72h_window_is_explicitly_unavailable():
    reading = parse_open_meteo_response(_hourly_fixture(hours=30), latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm == pytest.approx(24.0)
    assert reading.rainfall_72h_mm is None


def test_incomplete_24h_window_is_explicitly_unavailable():
    reading = parse_open_meteo_response(_hourly_fixture(hours=23), latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm is None
    assert reading.rainfall_72h_mm is None


def test_gap_inside_selected_window_makes_accumulation_unavailable():
    body = _hourly_fixture(hours=80)
    del body["hourly"]["time"][-10]
    del body["hourly"]["precipitation"][-10]
    reading = parse_open_meteo_response(body, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm is None
    assert reading.rainfall_72h_mm is None



def test_null_bucket_inside_selected_window_makes_accumulation_unavailable():
    body = _hourly_fixture(hours=80)
    body["hourly"]["precipitation"][-3] = None
    reading = parse_open_meteo_response(body, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm is None
    assert reading.rainfall_72h_mm is None

def test_missing_hourly_data_keeps_current_weather_but_accumulations_unavailable():
    body = _hourly_fixture()
    body.pop("hourly")
    reading = parse_open_meteo_response(body, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_mm == 2.4
    assert reading.rainfall_24h_mm is None
    assert reading.rainfall_72h_mm is None


def test_current_hour_bucket_is_not_counted_as_complete():
    body = _hourly_fixture(hours=24)
    body["hourly"]["time"].append(body["current"]["time"])
    body["hourly"]["precipitation"].append(999.0)
    reading = parse_open_meteo_response(body, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm == pytest.approx(24.0)



def test_current_time_is_floored_to_hour_for_complete_bucket_selection():
    cutoff = datetime.fromisoformat("2026-09-19T09:00")
    start = cutoff - timedelta(hours=24)
    body = _hourly_fixture(hours=24, current_time="2026-09-19T09:15")
    body["hourly"]["time"] = [(start + timedelta(hours=i)).isoformat(timespec="minutes") for i in range(24)]
    reading = parse_open_meteo_response(body, latitude=-6.2, longitude=106.8)
    assert reading.rainfall_24h_mm == pytest.approx(24.0)

def test_missing_current_key_raises_openmeteoerror():
    with pytest.raises(OpenMeteoError):
        parse_open_meteo_response({"latitude": 0, "longitude": 0}, latitude=0, longitude=0)


def test_missing_field_inside_current_raises():
    broken = _hourly_fixture()
    del broken["current"]["relative_humidity_2m"]
    with pytest.raises(OpenMeteoError):
        parse_open_meteo_response(broken, latitude=0, longitude=0)


def test_non_numeric_current_field_raises():
    broken = _hourly_fixture()
    broken["current"]["temperature_2m"] = "not-a-number"
    with pytest.raises(OpenMeteoError):
        parse_open_meteo_response(broken, latitude=0, longitude=0)
