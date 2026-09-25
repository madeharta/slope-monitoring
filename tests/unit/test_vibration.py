import math
from datetime import datetime, timedelta, timezone
from ml.domain.canonical_schema import CanonicalAccelSample
from ml.pipeline.feature_engineering.vibration import compute_vibration_metrics
_GRAVITY = 9.80665
def _synthetic_pulse(amplitude_mps2: float, freq_hz: float, n: int, dt: float) -> list[CanonicalAccelSample]:
    t0 = datetime(2026, 9, 15, 10, 30, 15, tzinfo=timezone.utc)
    samples = []
    for i in range(n):
        t = i * dt
        ax = amplitude_mps2 * math.sin(2 * math.pi * freq_hz * t)
        samples.append(
            CanonicalAccelSample(
                device_id="ROVER-01", sample_index=i, timestamp_utc=t0 + timedelta(seconds=t),
                adxl355_xyz_mps2=(ax, 0.0, _GRAVITY), mpu9250_xyz_mps2=(ax, 0.0, _GRAVITY),
                colocated_position=None,
            )
        )
    return samples
def test_ppa_matches_analytic_amplitude_after_gravity_detrend():
    amplitude, freq = 5.0, 25.0
    samples = _synthetic_pulse(amplitude, freq, n=200, dt=0.001)
    metrics = compute_vibration_metrics(samples, sensor="adxl355")
    expected_ppa_g = amplitude / _GRAVITY
    assert abs(metrics.ppa_g - expected_ppa_g) < 0.02
def test_ppv_matches_analytic_integral_of_sinusoid():
    amplitude, freq = 5.0, 25.0
    samples = _synthetic_pulse(amplitude, freq, n=200, dt=0.001)
    metrics = compute_vibration_metrics(samples, sensor="adxl355")
    expected_ppv_mm_s = (amplitude / (math.pi * freq)) * 1000
    assert abs(metrics.ppv_mm_s - expected_ppv_mm_s) / expected_ppv_mm_s < 0.01
def test_compute_vibration_metrics_rejects_empty_input():
    import pytest
    with pytest.raises(ValueError):
        compute_vibration_metrics([])
