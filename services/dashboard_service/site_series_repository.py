from __future__ import annotations
from datetime import datetime
from apps.api.config import ACTION, THRESHOLDS, status_for, worst
from common.errors import AppError, ErrorCode, NotFoundError
class SiteSeriesRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def get_series(
        self, site_id: str, hours: int,
        from_time: datetime | None = None, to_time: datetime | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            site = await conn.fetchrow("SELECT site_id FROM sites WHERE site_id = $1", site_id)
            if site is None:
                raise NotFoundError("site", site_id)
            if from_time is not None and to_time is not None:
                if from_time >= to_time:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "from_time harus lebih awal dari to_time")
                rows = await conn.fetch(
                    """
                    SELECT quantity, unit, time, value FROM measurements
                    WHERE site_id = $1 AND time BETWEEN $2 AND $3
                      AND (quantity NOT IN ('displacement', 'disp_e', 'disp_n', 'disp_u')
                           OR EXISTS (SELECT 1 FROM rover_displacement_baselines b
                                      WHERE b.device_id = measurements.device_id
                                        AND measurements.time >= b.approved_at))
                    ORDER BY quantity, time ASC
                    """,
                    site_id, from_time, to_time,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT quantity, unit, time, value FROM measurements
                    WHERE site_id = $1 AND time > now() - make_interval(hours => $2)
                      AND (quantity NOT IN ('displacement', 'disp_e', 'disp_n', 'disp_u')
                           OR EXISTS (SELECT 1 FROM rover_displacement_baselines b
                                      WHERE b.device_id = measurements.device_id
                                        AND measurements.time >= b.approved_at))
                    ORDER BY quantity, time ASC
                    """,
                    site_id, hours,
                )
        series_by_quantity: dict[str, dict] = {}
        for r in rows:
            q = r["quantity"]
            if q not in series_by_quantity:
                series_by_quantity[q] = {"quantity": q, "unit": r["unit"], "points": []}
            series_by_quantity[q]["points"].append([r["time"].isoformat(), r["value"]])
        statuses = []
        for q, s in series_by_quantity.items():
            latest_value = s["points"][-1][1] if s["points"] else None
            statuses.append(status_for(q, latest_value))
        site_status = worst(statuses) if statuses else "unknown"
        return {
            "series": list(series_by_quantity.values()),
            "status": site_status,
            "action": ACTION.get(site_status, "Data belum cukup untuk menetapkan status lereng."),
            "thresholds": THRESHOLDS,
            "sensors": [],
        }
