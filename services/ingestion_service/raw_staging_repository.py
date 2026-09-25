from __future__ import annotations
from datetime import datetime, timedelta
DEFAULT_EPOCH_TOLERANCE = timedelta(seconds=150)
class RawStagingRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def insert_gnss_raw(
        self, device_id: str, timestamp_utc: datetime, raw_payload_base64: str, file_name: str
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO gnss_raw_samples (time, device_id, raw_payload_base64, file_name)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (device_id, time) DO NOTHING
                """,
                timestamp_utc, device_id, raw_payload_base64, file_name,
            )
    async def insert_gnss_raw_batch(self, rows: list[tuple[str, datetime, bytes, str]]) -> None:
        import base64
        values = [
            (ts, device_id, base64.b64encode(raw).decode(), file_name)
            for device_id, ts, raw, file_name in rows
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO gnss_raw_samples (time, device_id, raw_payload_base64, file_name)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (device_id, time) DO NOTHING
                """,
                values,
            )
    async def find_nearest_base_epoch(
        self, base_device_id: str, target_time: datetime, tolerance: timedelta = DEFAULT_EPOCH_TOLERANCE,
    ) -> tuple[datetime, bytes] | None:
        import base64
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT time, raw_payload_base64 FROM gnss_raw_samples
                WHERE device_id = $1 AND time BETWEEN $2 AND $3
                ORDER BY abs(extract(epoch FROM (time - $4::timestamptz)))
                LIMIT 1
                """,
                base_device_id, target_time - tolerance, target_time + tolerance, target_time,
            )
        if row is None:
            return None
        return row["time"], base64.b64decode(row["raw_payload_base64"])
    async def insert_accel_raw_batch(
        self, device_id: str, samples: list, blast_command_id: int | None = None
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO accel_raw_samples
                    (time, device_id, sample_index, adxl355_x_mps2, adxl355_y_mps2, adxl355_z_mps2,
                     mpu9250_x_mps2, mpu9250_y_mps2, mpu9250_z_mps2, blast_command_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (device_id, time, sample_index) DO NOTHING
                """,
                [
                    (
                        s.timestamp_utc, device_id, s.sample_index,
                        *s.adxl355_xyz_mps2, *s.mpu9250_xyz_mps2, blast_command_id,
                    )
                    for s in samples
                ],
            )
