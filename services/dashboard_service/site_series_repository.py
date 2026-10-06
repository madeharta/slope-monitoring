"""Backs `GET /api/sites/{id}?hours=N` — response shape reverse-engineered
from apps/frontend/src/pages/SlopeDetail.jsx: `series[].{quantity,unit,points}`
where `points` is `[[isoTime, value], ...]` ascending — that exact nesting
(array-of-pairs, not array-of-objects) is what SlopeDetail.jsx's `byQ`
merge logic expects (`s.points.map((p) => [p[0], p[1]])`).

REVISED 2026-09-19 (real bug found via browser console — see
PROJECT_AUDIT_LOG.md): the FIRST version of this endpoint only returned
`series`, missing FOUR fields SlopeDetail.jsx actually reads —
`data.sensors` (no fallback, crashed the whole page:
`Cannot read properties of undefined (reading 'filter')` in the
CrossSection component), and `data.status`/`data.action`/`data.thresholds`
(had fallbacks, so didn't crash, but rendered wrong — "badge undefined",
threshold bands falling back to hardcoded frontend guesses instead of the
server's real configured values). This is exactly the class of mistake
the OverviewRepository build avoided by reading the frontend source
FIRST — this endpoint should have gotten the same treatment and didn't;
now it has, checked against every `data.X` usage in the file, not just
`series`.
"""

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
        """`from_time`/`to_time` (2026-09-22, baru — rentang tanggal
        kustom eksplisit, bukan cuma "N jam terakhir dari sekarang").
        Kalau KEDUANYA diisi, dipakai LANGSUNG (BETWEEN) — `hours`
        diabaikan. Kalau salah satu/tidak ada, fallback ke `hours`
        (perilaku LAMA, dipakai tombol preset 6h/24h/3d/7d) — supaya
        tombol yang sudah ada tetap jalan tanpa perubahan."""
        async with self._pool.acquire() as conn:
            site = await conn.fetchrow("SELECT site_id FROM sites WHERE site_id = $1", site_id)
            if site is None:
                raise NotFoundError("site", site_id)

            if from_time is not None and to_time is not None:
                if from_time >= to_time:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "from_time harus lebih awal dari to_time")
                rows = await conn.fetch(
                    """
                    SELECT device_id, quantity, unit, time, value FROM measurements
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
                # Same bug class as OverviewRepository's device query (see its
                # comment) — `$2 || ' hours'` would concatenate an INTEGER with
                # TEXT, which Postgres has no operator for. Fixed the same way:
                # make_interval(), never string-concatenate an interval.
                rows = await conn.fetch(
                    """
                    SELECT device_id, quantity, unit, time, value FROM measurements
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
        device_series_by_key: dict[tuple[str, str], dict] = {}
        latest_by_device_quantity: dict[tuple[str | None, str], float | None] = {}
        for r in rows:
            q = r["quantity"]
            device_id = r.get("device_id") if hasattr(r, "get") else None
            if q not in series_by_quantity:
                series_by_quantity[q] = {"quantity": q, "unit": r["unit"], "points": []}
            series_by_quantity[q]["points"].append([r["time"].isoformat(), r["value"]])
            if device_id is not None:
                key = (device_id, q)
                if key not in device_series_by_key:
                    device_series_by_key[key] = {
                        "device_id": device_id, "quantity": q, "unit": r["unit"], "points": [],
                    }
                device_series_by_key[key]["points"].append([r["time"].isoformat(), r["value"]])
            latest_by_device_quantity[(device_id, q)] = r["value"]

        # Evaluate technical status per device+quantity so two rover streams are
        # never collapsed before the worst-status reduction.
        statuses = [status_for(q, value) for (_device_id, q), value in latest_by_device_quantity.items()]
        site_status = worst(statuses) if statuses else "unknown"

        return {
            "series": list(series_by_quantity.values()),
            "device_series": list(device_series_by_key.values()),
            "status": site_status,
            "action": ACTION.get(site_status, "Data belum cukup untuk menetapkan status lereng."),
            "thresholds": THRESHOLDS,
            # Depth-based sensors (piezometer/soil moisture at various
            # depths) — genuinely don't exist on this system's hardware
            # (GNSS + accelerometer only, per API Spec LoRa/4G v1.3/v1.6).
            # Empty, not omitted: CrossSection expects an array, always.
            "sensors": [],
        }
