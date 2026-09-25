from __future__ import annotations
from dataclasses import dataclass
from common.errors import NotFoundError
@dataclass(frozen=True)
class BaseReferencePosition:
    device_id: str
    latitude: float
    longitude: float
    altitude_m: float
class ReferencePositionRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def get(self, device_id: str) -> BaseReferencePosition:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT latitude, longitude, altitude_m FROM device_reference_position WHERE device_id = $1",
                device_id,
            )
        if row is None:
            raise NotFoundError("device_reference_position", device_id)
        return BaseReferencePosition(
            device_id=device_id, latitude=row["latitude"], longitude=row["longitude"], altitude_m=row["altitude_m"],
        )
