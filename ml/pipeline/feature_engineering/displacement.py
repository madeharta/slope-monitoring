from __future__ import annotations
import math
from dataclasses import dataclass
_WGS84_A = 6_378_137.0
_WGS84_F = 1 / 298.257223563
_WGS84_E2 = _WGS84_F * (2 - _WGS84_F)
def geodetic_to_ecef(lat_deg: float, lon_deg: float, h_m: float) -> tuple[float, float, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    n = _WGS84_A / math.sqrt(1 - _WGS84_E2 * sin_lat**2)
    x = (n + h_m) * cos_lat * math.cos(lon)
    y = (n + h_m) * cos_lat * math.sin(lon)
    z = (n * (1 - _WGS84_E2) + h_m) * sin_lat
    return x, y, z
def ecef_delta_to_enu(dx: float, dy: float, dz: float, ref_lat_deg: float, ref_lon_deg: float) -> tuple[float, float, float]:
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
    rover_xyz = geodetic_to_ecef(rover_lat, rover_lon, rover_alt_m)
    base_xyz = geodetic_to_ecef(base_lat, base_lon, base_alt_m)
    dx, dy, dz = (rover_xyz[i] - base_xyz[i] for i in range(3))
    de_m, dn_m, du_m = ecef_delta_to_enu(dx, dy, dz, base_lat, base_lon)
    total_m = math.sqrt(de_m**2 + dn_m**2 + du_m**2)
    return DisplacementMM(de_mm=de_m * 1000, dn_mm=dn_m * 1000, du_mm=du_m * 1000, total_mm=total_m * 1000)
def meters_per_degree_lat(lat_deg: float) -> float:
    lat = math.radians(lat_deg)
    a, b, c, d = (111_132.92, -559.82, 1.175, -0.0023)
    return a + b * math.cos(2 * lat) + c * math.cos(4 * lat) + d * math.cos(6 * lat)
def meters_per_degree_lon(lat_deg: float) -> float:
    lat = math.radians(lat_deg)
    a, b, c = (111_412.84, -93.5, 0.118)
    return a * math.cos(lat) + b * math.cos(3 * lat) + c * math.cos(5 * lat)
