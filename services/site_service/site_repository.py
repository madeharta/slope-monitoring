from __future__ import annotations
import math
from dataclasses import dataclass
from common.errors import AppError, ErrorCode, NotFoundError
_EARTH_RADIUS_M = 6_371_000.0
_PROXIMITY_WARNING_M = 100.0
class DuplicateSiteWarning(AppError):
    def __init__(self, nearby: list[dict]) -> None:
        names = ", ".join(f"{n['site_id']} ({n['distance_m']:.0f}m)" for n in nearby)
        super().__init__(
            ErrorCode.VALIDATION_ERROR,
            f"site baru berjarak <{_PROXIMITY_WARNING_M:.0f}m dari site existing: {names} — "
            f"kirim ulang dengan force=true kalau ini memang site berbeda",
        )
def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))
@dataclass(frozen=True)
class NewSite:
    site_id: str
    name: str
    lat: float
    lon: float
class SiteRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def find_nearby(self, lat: float, lon: float, within_m: float = _PROXIMITY_WARNING_M) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT site_id, name, lat, lon FROM sites")
        nearby = []
        for r in rows:
            d = haversine_distance_m(lat, lon, r["lat"], r["lon"])
            if d <= within_m:
                nearby.append({"site_id": r["site_id"], "name": r["name"], "distance_m": d})
        return sorted(nearby, key=lambda x: x["distance_m"])
    async def create(self, site: NewSite, force: bool = False) -> None:
        if not force:
            nearby = await self.find_nearby(site.lat, site.lon)
            if nearby:
                raise DuplicateSiteWarning(nearby)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sites (site_id, name, lat, lon) VALUES ($1, $2, $3, $4)",
                site.site_id, site.name, site.lat, site.lon,
            )
    async def update(self, site_id: str, name: str, lat: float, lon: float) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE sites SET name = $2, lat = $3, lon = $4 WHERE site_id = $1", site_id, name, lat, lon,
            )
        if result == "UPDATE 0":
            raise NotFoundError("site", site_id)
