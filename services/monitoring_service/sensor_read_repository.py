from __future__ import annotations

import math
from datetime import datetime
from typing import Any

DEFAULT_MAX_POINTS = 2000
HARD_MAX_POINTS = 5000


def bounded_stride(total_samples: int, max_points: int) -> int:
    """Deterministic display-only downsampling. Raw rows remain authoritative."""
    if total_samples <= 0:
        return 1
    bounded = max(2, min(int(max_points), HARD_MAX_POINTS))
    return max(1, math.ceil(total_samples / bounded))


class SensorReadRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def list_gnss(self, *, site_id: str, device_id: str | None,
                        from_time: datetime | None, to_time: datetime | None,
                        limit: int) -> list:
        clauses = ["p.site_id = $1"]
        args: list[Any] = [site_id]
        if device_id:
            args.append(device_id)
            clauses.append(f"p.device_id = ${len(args)}")
        if from_time:
            args.append(from_time)
            clauses.append(f"p.time >= ${len(args)}")
        if to_time:
            args.append(to_time)
            clauses.append(f"p.time <= ${len(args)}")
        args.append(max(1, min(int(limit), HARD_MAX_POINTS)))
        query = f"""
            SELECT p.time, p.device_id, p.site_id, p.latitude, p.longitude,
                   p.altitude_m, p.gnss_fix_type, p.h_acc_m, p.source_kind,
                   p.validation_status, p.source_file,
                   f.upload_origin, f.received_at AS source_received_at
            FROM device_position_records p
            LEFT JOIN file_uploads f ON f.file_name = p.source_file
            WHERE {' AND '.join(clauses)}
            ORDER BY p.time DESC
            LIMIT ${len(args)}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return list(reversed(rows))

    async def list_accel_events(self, *, site_id: str | None,
                                device_id: str | None, limit: int) -> list:
        clauses, args = [], []
        if site_id:
            args.append(site_id)
            clauses.append(f"e.site_id = ${len(args)}")
        if device_id:
            args.append(device_id)
            clauses.append(f"e.device_id = ${len(args)}")
        args.append(max(1, min(int(limit), 200)))
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT e.event_id, e.site_id, e.device_id, e.blast_command_id,
                   e.source_file, e.communication_mode, e.schema_version,
                   e.event_start, e.event_end, e.sample_count, e.duration_ms,
                   e.observed_sample_rate_hz, e.median_gap_ms, e.max_gap_ms,
                   e.quality_gate_status, e.quality_reasons,
                   e.adxl355_ppa_g, e.adxl355_ppv_mm_s,
                   e.mpu9250_ppa_g, e.mpu9250_ppv_mm_s,
                   e.validation_status, f.upload_origin,
                   f.received_at AS source_received_at
            FROM blast_event_records e
            LEFT JOIN file_uploads f ON f.file_name = e.source_file
            {where}
            ORDER BY e.event_start DESC
            LIMIT ${len(args)}
        """
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def get_accel_waveform(self, *, file_name: str,
                                 device_id: str | None,
                                 max_points: int) -> dict:
        clauses = ["file_name = $1"]
        args: list[Any] = [file_name]
        if device_id:
            args.append(device_id)
            clauses.append(f"device_id = ${len(args)}")
        where = " AND ".join(clauses)

        async with self._pool.acquire() as conn:
            total = int(await conn.fetchval(
                f"SELECT count(*) FROM accel_raw_samples WHERE {where}", *args
            ) or 0)
            if total == 0:
                return {"total_samples": 0, "returned_samples": 0,
                        "stride": 1, "rows": []}

            stride = bounded_stride(total, max_points)
            query = f"""
                WITH ordered AS (
                    SELECT time, device_id, sample_index,
                           adxl355_x_mps2, adxl355_y_mps2, adxl355_z_mps2,
                           mpu9250_x_mps2, mpu9250_y_mps2, mpu9250_z_mps2,
                           blast_command_id, file_name,
                           row_number() OVER (ORDER BY time, sample_index) AS rn,
                           count(*) OVER () AS n
                    FROM accel_raw_samples
                    WHERE {where}
                )
                SELECT time, device_id, sample_index,
                       adxl355_x_mps2, adxl355_y_mps2, adxl355_z_mps2,
                       mpu9250_x_mps2, mpu9250_y_mps2, mpu9250_z_mps2,
                       blast_command_id, file_name
                FROM ordered
                WHERE rn = 1 OR rn = n OR mod(rn - 1, ${len(args)+1}) = 0
                ORDER BY time, sample_index
            """
            rows = await conn.fetch(query, *args, stride)
        return {"total_samples": total, "returned_samples": len(rows),
                "stride": stride, "rows": rows}
