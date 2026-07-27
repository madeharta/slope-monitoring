from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from common.schema import Envelope, Location, Reading
from common.topics import SUBSCRIBE_ALL, build_topic, parse_topic


def _envelope(**overrides):
    base = dict(
        device_id="esp32-lereng-a-01",
        device_type="esp32",
        site_id="lereng-a",
        timestamp=datetime(2026, 7, 27, 9, 15, 0, 123456, tzinfo=UTC),
        location=Location(lat=-6.3643, lon=106.829),
        readings=[Reading(quantity="soil_moisture", value=32.4, unit="pct", depth_cm=30.0)],
    )
    base.update(overrides)
    return Envelope(**base)


def test_round_trip_preserves_subsecond_and_tz():
    env = _envelope()
    parsed = Envelope.from_json(env.to_json())
    assert parsed == env
    assert parsed.timestamp.microsecond == 123456
    assert parsed.timestamp.tzinfo is not None


def test_quality_flag_defaults_to_ok():
    r = Reading(quantity="soil_moisture", value=1.0, unit="pct", depth_cm=30.0)
    assert r.quality_flag == "ok"


def test_depth_cm_is_a_required_key_but_may_be_null():
    # Must be provided (always present)...
    with pytest.raises(ValidationError):
        Reading(quantity="tilt_x", value=0.3, unit="deg")  # type: ignore[call-arg]
    # ...but null is allowed for surface / non-depth sensors.
    assert Reading(quantity="tilt_x", value=0.3, unit="deg", depth_cm=None).depth_cm is None


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError):
        _envelope(timestamp=datetime(2026, 7, 27, 9, 15, 0))


def test_empty_readings_rejected():
    with pytest.raises(ValidationError):
        _envelope(readings=[])


def test_bad_value_allowed_with_quality_flag():
    r = Reading(quantity="soil_moisture", value=None, unit="pct", depth_cm=30.0, quality_flag="nan")
    assert r.value is None and r.quality_flag == "nan"


def test_topic_build_and_parse_round_trip():
    topic = build_topic("lereng-a", "esp32-lereng-a-01")
    assert topic == "slope/lereng-a/esp32-lereng-a-01/data"
    assert parse_topic(topic) == ("lereng-a", "esp32-lereng-a-01")


def test_topic_rejects_wildcards_in_ids():
    with pytest.raises(ValueError):
        build_topic("lereng-a", "dev+ice")
    with pytest.raises(ValueError):
        parse_topic(SUBSCRIBE_ALL)
