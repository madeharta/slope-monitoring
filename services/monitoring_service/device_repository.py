from __future__ import annotations
from common.errors import NotFoundError
class DeviceRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def get_site_id(self, device_id: str) -> str:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT site_id FROM devices WHERE device_id = $1", device_id)
        if row is None:
            raise NotFoundError("device", device_id)
        return row["site_id"]
    async def get_base_device_id_for_site(self, site_id: str) -> str:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT device_id FROM devices WHERE site_id = $1 AND device_type = 'gnss_base' LIMIT 1", site_id,
            )
        if row is None:
            raise NotFoundError("gnss_base device for site", site_id)
        return row["device_id"]
