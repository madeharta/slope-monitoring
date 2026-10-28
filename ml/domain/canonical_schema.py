"""Canonical Data Model — blueprint §4.2.

Unifies heterogeneous LoRa/4G output into one in-memory shape. `source` is
kept as provenance metadata for audit only; nothing downstream branches on
it — that is the whole point of this module existing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DeviceRole(str, Enum):
    BASE = "base"
    ROVER = "rover"


class PositionSource(str, Enum):
    RAWX_PPK = "rawx_ppk"      # base always; rover on 4G
    RTK_DIRECT = "rtk_direct"  # rover on LoRa (no onboard PPK — API Spec LoRa §11)


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
    battery_voltage_v: float | None = None


@dataclass(frozen=True)
class CanonicalAccelSample:
    device_id: str
    sample_index: int
    timestamp_utc: datetime
    adxl355_xyz_mps2: tuple[float, float, float]
    mpu9250_xyz_mps2: tuple[float, float, float]
    colocated_position: CanonicalPositionSample | None  # fill-forward RTK/RAWX, may be absent pre-fix


@dataclass(frozen=True)
class Displacement:
    """Output of blueprint §4.3 — written to `measurements` as
    quantity in {displacement, disp_e, disp_n, disp_u}."""

    device_id: str
    timestamp_utc: datetime
    de_mm: float
    dn_mm: float
    du_mm: float
    total_mm: float
