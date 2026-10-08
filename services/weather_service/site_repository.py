from __future__ import annotations
from common.errors import NotFoundError
class SiteRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def get_coordinates(self, site_id: str) -> tuple[float, float]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT lat, lon FROM sites WHERE site_id = $1", site_id)
        if row is None:
            raise NotFoundError("site", site_id)
        return row["lat"], row["lon"]
