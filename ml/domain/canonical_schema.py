from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
class DeviceRole(str, Enum):
    BASE = "base"
    ROVER = "rover"
class PositionSource(str, Enum):
    RAWX_PPK = "rawx_ppk"
    RTK_DIRECT = "rtk_direct"
@dataclass(frozen=True)
class CanonicalPositionSample:
    device_id: str
    role: DeviceRole
    timestamp_utc: datetime
    latitude: float
    longitude: float
    altitude_m: float
    gnss_fix_type: int
    h_acc_m: float
    source: PositionSource
@dataclass(frozen=True)
class CanonicalAccelSample:
    device_id: str
    sample_index: int
    timestamp_utc: datetime
    adxl355_xyz_mps2: tuple[float, float, float]
    mpu9250_xyz_mps2: tuple[float, float, float]
    colocated_position: CanonicalPositionSample | None
@dataclass(frozen=True)
class Displacement:
    device_id: str
    timestamp_utc: datetime
    de_mm: float
    dn_mm: float
    du_mm: float
    total_mm: float
