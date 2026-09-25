from __future__ import annotations
import math
from datetime import datetime, timezone
import pytest
from ml.domain.canonical_schema import CanonicalAccelSample
from ml.pipeline.feature_engineering.tilt import compute_tilt
_G = 9.80665
def _sample(x: float, y: float, z: float) -> CanonicalAccelSample:
    return CanonicalAccelSample(
        device_id="ROVER-01", sample_index=0, timestamp_utc=datetime.now(timezone.utc),
        adxl355_xyz_mps2=(x, y, z), mpu9250_xyz_mps2=(x, y, z), colocated_position=None,
    )
def test_flat_orientation_is_zero_tilt():
    result = compute_tilt([_sample(0.0, 0.0, _G)])
    assert abs(result.tilt_x_deg) < 1e-9
    assert abs(result.tilt_y_deg) < 1e-9
def test_90_degree_tilt_on_x_axis():
    result = compute_tilt([_sample(_G, 0.0, 0.0)])
    assert abs(result.tilt_x_deg - 90.0) < 1e-9
def test_90_degree_tilt_on_y_axis():
    result = compute_tilt([_sample(0.0, _G, 0.0)])
    assert abs(result.tilt_y_deg - 90.0) < 1e-9
def test_45_degree_tilt_evenly_split():
    half = _G / math.sqrt(2)
    result = compute_tilt([_sample(half, 0.0, half)])
    assert abs(result.tilt_x_deg - 45.0) < 1e-9
def test_averages_across_samples_not_just_last():
    result = compute_tilt([_sample(_G, 0.0, 0.0), _sample(-_G, 0.0, 0.0)])
    assert abs(result.tilt_x_deg) < 1e-6
def test_empty_samples_raises():
    with pytest.raises(ValueError):
        compute_tilt([])
def test_unknown_sensor_raises():
    with pytest.raises(ValueError):
        compute_tilt([_sample(0.0, 0.0, _G)], sensor="unknown")
def test_mpu9250_sensor_selection():
    s = CanonicalAccelSample(
        device_id="ROVER-01", sample_index=0, timestamp_utc=datetime.now(timezone.utc),
        adxl355_xyz_mps2=(0.0, 0.0, _G), mpu9250_xyz_mps2=(_G, 0.0, 0.0), colocated_position=None,
    )
    flat = compute_tilt([s], sensor="adxl355")
    tilted = compute_tilt([s], sensor="mpu9250")
    assert abs(flat.tilt_x_deg) < 1e-9
    assert abs(tilted.tilt_x_deg - 90.0) < 1e-9
