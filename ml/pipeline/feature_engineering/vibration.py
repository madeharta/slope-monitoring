"""Accelerometer event metrics and QA.

The device sends high-rate acceleration windows (nominally ~1000 Hz) from
ADXL355 and MPU9250. These functions deliberately keep engineering metrics
separate from field-safety claims: PPA/PPV are technical event features and
remain unvalidated until an accepted field methodology/baseline exists.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from ml.domain.canonical_schema import CanonicalAccelSample

_GRAVITY_MPS2 = 9.80665

@dataclass(frozen=True)
class VibrationMetrics:
    ppa_g: float
    ppv_mm_s: float
    sample_count: int

@dataclass(frozen=True)
class AccelWindowQuality:
    sample_count: int
    duration_ms: float
    observed_sample_rate_hz: float | None
    median_gap_ms: float | None
    max_gap_ms: float | None
    quality_gate_status: str
    reasons: tuple[str, ...]

def analyze_accel_window(
    samples: list[CanonicalAccelSample],
    *,
    expected_rate_hz: float = 1000.0,
    rate_tolerance_fraction: float = 0.20,
    max_gap_factor: float = 5.0,
    min_samples: int = 20,
) -> AccelWindowQuality:
    if not samples:
        return AccelWindowQuality(0, 0.0, None, None, None, "rejected", ("empty_window",))

    reasons: list[str] = []
    if len({s.sample_index for s in samples}) != len(samples):
        reasons.append("duplicate_sample_index")
    if any(samples[i].sample_index <= samples[i-1].sample_index for i in range(1, len(samples))):
        reasons.append("sample_index_not_strictly_increasing")

    times = [s.timestamp_utc.timestamp() for s in samples]
    dts = [times[i] - times[i-1] for i in range(1, len(times))]
    if any(dt <= 0 for dt in dts):
        reasons.append("timestamp_not_strictly_increasing")

    positive_dts = [dt for dt in dts if dt > 0]
    median_dt = statistics.median(positive_dts) if positive_dts else None
    max_dt = max(positive_dts) if positive_dts else None
    duration_s = max(0.0, times[-1] - times[0]) if len(times) > 1 else 0.0
    observed_rate = (1.0 / median_dt) if median_dt and median_dt > 0 else None

    if len(samples) < min_samples:
        reasons.append("too_few_samples")
    if observed_rate is not None:
        lo = expected_rate_hz * (1 - rate_tolerance_fraction)
        hi = expected_rate_hz * (1 + rate_tolerance_fraction)
        if not (lo <= observed_rate <= hi):
            reasons.append("sample_rate_outside_nominal_tolerance")
    if median_dt and max_dt and max_dt > median_dt * max_gap_factor:
        reasons.append("large_sampling_gap")

    rejected_reasons = {
        "empty_window", "duplicate_sample_index",
        "sample_index_not_strictly_increasing", "timestamp_not_strictly_increasing",
    }
    if any(r in rejected_reasons for r in reasons):
        status = "rejected"
    elif reasons:
        status = "degraded"
    else:
        status = "accepted"

    return AccelWindowQuality(
        sample_count=len(samples),
        duration_ms=duration_s * 1000.0,
        observed_sample_rate_hz=observed_rate,
        median_gap_ms=(median_dt * 1000.0 if median_dt is not None else None),
        max_gap_ms=(max_dt * 1000.0 if max_dt is not None else None),
        quality_gate_status=status,
        reasons=tuple(reasons),
    )

def _detrend(values: list[float]) -> list[float]:
    mean = sum(values) / len(values)
    return [v - mean for v in values]

def compute_vibration_metrics(samples: list[CanonicalAccelSample], sensor: str = "adxl355") -> VibrationMetrics:
    if not samples:
        raise ValueError("compute_vibration_metrics requires at least one sample")
    quality = analyze_accel_window(samples, min_samples=2)
    if quality.quality_gate_status == "rejected":
        raise ValueError("accelerometer window is not strictly ordered/unique")

    if sensor == "adxl355":
        xs = [s.adxl355_xyz_mps2[0] for s in samples]
        ys = [s.adxl355_xyz_mps2[1] for s in samples]
        zs = [s.adxl355_xyz_mps2[2] for s in samples]
    elif sensor == "mpu9250":
        xs = [s.mpu9250_xyz_mps2[0] for s in samples]
        ys = [s.mpu9250_xyz_mps2[1] for s in samples]
        zs = [s.mpu9250_xyz_mps2[2] for s in samples]
    else:
        raise ValueError(f"unknown sensor '{sensor}' (expected adxl355|mpu9250)")

    xs, ys, zs = _detrend(xs), _detrend(ys), _detrend(zs)
    resultant_accel = [math.sqrt(x*x + y*y + z*z) for x, y, z in zip(xs, ys, zs, strict=True)]
    ppa_g = max(resultant_accel) / _GRAVITY_MPS2

    t = [s.timestamp_utc.timestamp() for s in samples]
    vx = _cumulative_trapezoid(xs, t)
    vy = _cumulative_trapezoid(ys, t)
    vz = _cumulative_trapezoid(zs, t)
    resultant_velocity_mps = [math.sqrt(a*a + b*b + c*c) for a, b, c in zip(vx, vy, vz, strict=True)]
    ppv_mm_s = max(resultant_velocity_mps) * 1000.0
    return VibrationMetrics(ppa_g=ppa_g, ppv_mm_s=ppv_mm_s, sample_count=len(samples))

def _cumulative_trapezoid(values: list[float], t: list[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(values)):
        dt = t[i] - t[i - 1]
        out.append(out[-1] + 0.5 * (values[i] + values[i - 1]) * dt)
    return out
