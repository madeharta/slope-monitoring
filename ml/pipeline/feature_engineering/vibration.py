from __future__ import annotations
import math
from dataclasses import dataclass
from ml.domain.canonical_schema import CanonicalAccelSample
_GRAVITY_MPS2 = 9.80665
@dataclass(frozen=True)
class VibrationMetrics:
    ppa_g: float
    ppv_mm_s: float
    sample_count: int
def _detrend(values: list[float]) -> list[float]:
    mean = sum(values) / len(values)
    return [v - mean for v in values]
def compute_vibration_metrics(samples: list[CanonicalAccelSample], sensor: str = "adxl355") -> VibrationMetrics:
    if not samples:
        raise ValueError("compute_vibration_metrics requires at least one sample")
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
    resultant_accel = [math.sqrt(x**2 + y**2 + z**2) for x, y, z in zip(xs, ys, zs, strict=True)]
    ppa_g = max(resultant_accel) / _GRAVITY_MPS2
    t = [s.timestamp_utc.timestamp() for s in samples]
    vx = _cumulative_trapezoid(xs, t)
    vy = _cumulative_trapezoid(ys, t)
    vz = _cumulative_trapezoid(zs, t)
    resultant_velocity_mps = [math.sqrt(a**2 + b**2 + c**2) for a, b, c in zip(vx, vy, vz, strict=True)]
    ppv_mm_s = max(resultant_velocity_mps) * 1000
    return VibrationMetrics(ppa_g=ppa_g, ppv_mm_s=ppv_mm_s, sample_count=len(samples))
def _cumulative_trapezoid(values: list[float], t: list[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(values)):
        dt = t[i] - t[i - 1]
        out.append(out[-1] + 0.5 * (values[i] + values[i - 1]) * dt)
    return out
