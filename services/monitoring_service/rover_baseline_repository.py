from dataclasses import dataclass
from common.errors import NotFoundError
@dataclass(frozen=True)
class RoverBaseline:
    latitude: float
    longitude: float
    altitude_m: float
    vertical_datum: str
    max_h_acc_m: float
class RoverBaselineRepository:
    def __init__(self, pool):
        self._pool = pool
    async def get(self, device_id: str) -> RoverBaseline:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT latitude, longitude, altitude_m, vertical_datum, max_h_acc_m "
                "FROM rover_displacement_baselines "
                "WHERE device_id = $1 AND approved_at IS NOT NULL", device_id,
            )
        if row is None:
            raise NotFoundError("rover_displacement_baselines", device_id)
        return RoverBaseline(row["latitude"], row["longitude"], row["altitude_m"], row["vertical_datum"], row["max_h_acc_m"])
