from __future__ import annotations


class DevicePositionRepository:
    """Persistence for direct GNSS positions used by the device map.

    This table is deliberately separate from displacement measurements: a
    valid GNSS coordinate is useful for locating a device, but it does not by
    itself make deformation/displacement production-valid.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def write_rtk_direct(self, *, site_id: str, sample) -> None:
        if sample.gnss_fix_type <= 0:
            return
        if not (-90 <= sample.latitude <= 90 and -180 <= sample.longitude <= 180):
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO device_position_records (
                    time, device_id, site_id, latitude, longitude, altitude_m,
                    gnss_fix_type, h_acc_m, source_kind, validation_status
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'rtk_direct', 'unvalidated')
                ON CONFLICT (device_id, time, source_kind) DO UPDATE SET
                    site_id = EXCLUDED.site_id,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    altitude_m = EXCLUDED.altitude_m,
                    gnss_fix_type = EXCLUDED.gnss_fix_type,
                    h_acc_m = EXCLUDED.h_acc_m,
                    validation_status = 'unvalidated',
                    processed_at = now()
                """,
                sample.timestamp_utc,
                sample.device_id,
                site_id,
                sample.latitude,
                sample.longitude,
                sample.altitude_m,
                sample.gnss_fix_type,
                sample.h_acc_m,
            )
