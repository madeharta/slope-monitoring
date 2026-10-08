from __future__ import annotations
import math
from dataclasses import dataclass
from ml.domain.canonical_schema import CanonicalAccelSample
@dataclass(frozen=True)
class TiltDeg:
    tilt_x_deg: float
    tilt_y_deg: float
    sample_count: int
def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
def compute_tilt(samples: list[CanonicalAccelSample], sensor: str = "adxl355") -> TiltDeg:
    if not samples:
        raise ValueError("compute_tilt requires at least one sample")
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
    x, y, z = _mean(xs), _mean(ys), _mean(zs)
    tilt_x = math.degrees(math.atan2(x, math.sqrt(y**2 + z**2)))
    tilt_y = math.degrees(math.atan2(y, math.sqrt(x**2 + z**2)))
    return TiltDeg(tilt_x_deg=tilt_x, tilt_y_deg=tilt_y, sample_count=len(samples))
