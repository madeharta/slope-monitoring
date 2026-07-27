"""Sites, device profiles, and deterministic placement.

Coordinates cluster around real West Java slope locations — never
`random.uniform(-90, 90)` (the prior work's bug, which scattered sensors
across the globe and made any spatial view meaningless, context.md §7).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import timedelta, timezone

# Project-local timezone (WIB, UTC+7). Timestamps are tz-aware regardless.
WIB = timezone(timedelta(hours=7))


@dataclass(frozen=True)
class Site:
    site_id: str
    name: str
    lat: float
    lon: float


# Real-ish slope monitoring sites, clustered (West Java). Extend as needed.
SITES: dict[str, Site] = {
    "lereng-a": Site("lereng-a", "Lereng A (Depok)", -6.3643, 106.8290),
    "lereng-b": Site("lereng-b", "Lereng B (Bogor)", -6.5950, 106.8060),
}


@dataclass(frozen=True)
class QuantitySpec:
    quantity: str
    unit: str
    depth_cm: float | None


@dataclass(frozen=True)
class DeviceProfile:
    device_type: str
    quantities: tuple[QuantitySpec, ...]


# Minimal profile used by the smoke test; the full heterogeneous mix
# (tilt, rain gauge, piezometer, multi-depth) arrives with the device layer.
ESP32_SOIL = DeviceProfile(
    device_type="esp32",
    quantities=(QuantitySpec("soil_moisture", "pct", 30.0),),
)


def _meters_to_deg(dx_m: float, dy_m: float, lat: float) -> tuple[float, float]:
    """Convert a local metre offset to a (dlat, dlon) degree offset."""
    dlat = dy_m / 111_320.0
    dlon = dx_m / (111_320.0 * math.cos(math.radians(lat)))
    return dlat, dlon


def jittered_location(
    site: Site, rng: random.Random, radius_m: float = 150.0
) -> tuple[float, float]:
    """A deterministic point within `radius_m` of the site centre."""
    r = radius_m * math.sqrt(rng.random())
    theta = rng.uniform(0.0, 2.0 * math.pi)
    dlat, dlon = _meters_to_deg(r * math.cos(theta), r * math.sin(theta), site.lat)
    return site.lat + dlat, site.lon + dlon


def device_rng(seed: int, device_id: str) -> random.Random:
    """A per-device RNG derived deterministically from the run seed and the
    device id, so every run with the same seed is byte-for-byte reproducible."""
    return random.Random(f"{seed}:{device_id}")
