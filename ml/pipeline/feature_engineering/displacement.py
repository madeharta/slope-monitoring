"""Displacement formula — blueprint §4.3, REVISED 2026-09-18.

CORRECTION HISTORY: the original implementation used a degree-to-meter
approximation (meter_per_degree * delta-degrees), matching API Spec
§11.1's stated formula. ITB confirmed that formula is wrong for this
system's precision requirements. Root cause: a degree-based approximation
projects lat/lon onto a *local* meter scale independently per axis, which
is adequate for routing/mapping but introduces distortion at the
millimeter scale this system targets (the approximation itself is
accurate to sub-mm in the *coefficients*, but the underlying projection
model — treating E and N as independent degree-scaled axes — is not the
geodetically rigorous transform for a precise 3D baseline vector).

FIX: proper ECEF -> ENU (Local Tangent Plane) transform, computed as
    1. Convert both rover and base geodetic (lat, lon, h) to ECEF (X, Y, Z)
       on the WGS-84 ellipsoid.
    2. Take the ECEF difference vector (rover - base).
    3. Rotate that vector into the base's local East-North-Up frame via
       the standard geodetic rotation matrix.
This is the standard approach in RTK/PPK-based deformation monitoring —
see Hamza, V., Stopar, B., Sterle, O., Pavlovčič Prešeren, P. (2023).
"A Cost-Effective GNSS Solution for Continuous Monitoring of Landslides."
Remote Sensing, 15, 2287 (explicitly RTKLIB-based); and Shu, B. et al.
(2023). "Real-time high-precision landslide displacement monitoring
based on a GNSS CORS network." Measurement, 217, 113056 (reports
displacement directly in E/N/U components). The ECEF->ENU rotation
itself is standard geodesy (e.g. Hofmann-Wellenhof et al., "GNSS –
Global Navigation Satellite Systems", Springer) — not something a single
paper originates, but these two papers confirm it is the convention this
specific application domain (GNSS landslide/slope deformation) uses,
not just a generic geodesy footnote.

NOTE on prior citations: an earlier internal draft justification for this
change cited five papers (Chen et al. 2024 IEEE TGRS, Li/Zhang/Huang 2022
Remote Sensing, Liu et al. 2023 Acta Geotechnica, Wang et al. 2023
Engineering Geology, Jiang et al. 2022 Computers & Geosciences) that could
NOT be located in a literature search — title, authors, and journal/volume
did not match any indexed publication for 4 of the 5 checked. They are not
used here. Only the two verified references above are cited.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# WGS-84 ellipsoid constants.
_WGS84_A = 6_378_137.0            # semi-major axis, meters
_WGS84_F = 1 / 298.257223563       # flattening
_WGS84_E2 = _WGS84_F * (2 - _WGS84_F)  # first eccentricity squared


def geodetic_to_ecef(lat_deg: float, lon_deg: float, h_m: float) -> tuple[float, float, float]:
    """Geodetic (lat, lon, ellipsoidal height) -> ECEF (X, Y, Z), meters.
    Standard closed-form formula (no iteration needed for the forward
    direction geodetic->ECEF, unlike the reverse)."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    n = _WGS84_A / math.sqrt(1 - _WGS84_E2 * sin_lat**2)  # prime vertical radius of curvature

    x = (n + h_m) * cos_lat * math.cos(lon)
    y = (n + h_m) * cos_lat * math.sin(lon)
    z = (n * (1 - _WGS84_E2) + h_m) * sin_lat
    return x, y, z


def ecef_delta_to_enu(dx: float, dy: float, dz: float, ref_lat_deg: float, ref_lon_deg: float) -> tuple[float, float, float]:
    """Rotates an ECEF difference vector into the local East-North-Up
    frame at reference point (ref_lat, ref_lon) — the standard geodetic
    rotation matrix. `ref_lat`/`ref_lon` should be the FIXED point (base
    station), so the local tangent plane origin stays constant across
    epochs — a trend over time then reflects rover movement, not a
    shifting projection origin."""
    lat = math.radians(ref_lat_deg)
    lon = math.radians(ref_lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)

    e = -sin_lon * dx + cos_lon * dy
    n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    u = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    return e, n, u


@dataclass(frozen=True)
class DisplacementMM:
    de_mm: float
    dn_mm: float
    du_mm: float
    total_mm: float


def compute_displacement_mm(
    rover_lat: float, rover_lon: float, rover_alt_m: float,
    base_lat: float, base_lon: float, base_alt_m: float,
) -> DisplacementMM:
    """ECEF -> ENU displacement (see module docstring for correction
    history and references). `base_lat`/`base_lon` is the fixed, surveyed
    reference point — the local tangent plane origin."""
    rover_xyz = geodetic_to_ecef(rover_lat, rover_lon, rover_alt_m)
    base_xyz = geodetic_to_ecef(base_lat, base_lon, base_alt_m)
    dx, dy, dz = (rover_xyz[i] - base_xyz[i] for i in range(3))

    de_m, dn_m, du_m = ecef_delta_to_enu(dx, dy, dz, base_lat, base_lon)
    total_m = math.sqrt(de_m**2 + dn_m**2 + du_m**2)
    return DisplacementMM(de_mm=de_m * 1000, dn_mm=dn_m * 1000, du_mm=du_m * 1000, total_mm=total_m * 1000)


# Retained for backward compatibility with any code/tests still importing
# these — no longer used internally by compute_displacement_mm (kept as
# thin wrappers, not the primary computation path, since ECEF->ENU above
# supersedes them per the correction).
def meters_per_degree_lat(lat_deg: float) -> float:
    lat = math.radians(lat_deg)
    a, b, c, d = (111_132.92, -559.82, 1.175, -0.0023)
    return a + b * math.cos(2 * lat) + c * math.cos(4 * lat) + d * math.cos(6 * lat)


def meters_per_degree_lon(lat_deg: float) -> float:
    lat = math.radians(lat_deg)
    a, b, c = (111_412.84, -93.5, 0.118)
    return a * math.cos(lat) + b * math.cos(3 * lat) + c * math.cos(5 * lat)
