from __future__ import annotations
from apps.api.config import ACTION, THRESHOLDS, status_for, worst
_ONLINE_WINDOW_SECONDS = 900
class OverviewRepository:
    def __init__(self, pool) -> None:
        self._pool = pool
    async def get_overview(self) -> dict:
        async with self._pool.acquire() as conn:
            sites = await conn.fetch("SELECT site_id, name, lat, lon FROM sites")
            devices = await conn.fetch(
                "SELECT device_id, site_id, "
                "(last_seen IS NOT NULL AND last_seen > now() - make_interval(secs => $1)) AS online "
                "FROM devices",
                _ONLINE_WINDOW_SECONDS,
            )
            quantities = list(THRESHOLDS.keys())
            latest_readings = await conn.fetch(
                """
                SELECT DISTINCT ON (device_id, quantity)
                    device_id, site_id, quantity, value, unit, time
                FROM measurements
                WHERE quantity = ANY($1::text[])
                  AND (quantity NOT IN ('displacement', 'disp_e', 'disp_n', 'disp_u')
                       OR EXISTS (SELECT 1 FROM rover_displacement_baselines b
                                  WHERE b.device_id = measurements.device_id
                                    AND measurements.time >= b.approved_at))
                ORDER BY device_id, quantity, time DESC
                """,
                quantities,
            )
        site_by_id = {s["site_id"]: s for s in sites}
        devices_by_site: dict[str, list] = {}
        for d in devices:
            devices_by_site.setdefault(d["site_id"], []).append(d)
        readings_by_site: dict[str, list] = {}
        for r in latest_readings:
            readings_by_site.setdefault(r["site_id"], []).append(r)
        slopes = []
        status_counts = {"normal": 0, "siaga": 0, "bahaya": 0, "unknown": 0}
        online_total = offline_total = 0
        for site_id, site in site_by_id.items():
            site_readings = readings_by_site.get(site_id, [])
            statuses = [status_for(r["quantity"], r["value"]) for r in site_readings]
            site_status = worst(statuses) if statuses else "unknown"
            status_counts[site_status] += 1
            representative = None
            for r in site_readings:
                if status_for(r["quantity"], r["value"]) == site_status:
                    representative = r
                    break
            site_devices = devices_by_site.get(site_id, [])
            online_total += sum(1 for d in site_devices if d["online"])
            offline_total += sum(1 for d in site_devices if not d["online"])
            slopes.append({
                "site_id": site_id, "name": site["name"], "lat": site["lat"], "lon": site["lon"],
                "status": site_status, "action": ACTION.get(site_status, "Data belum cukup untuk menetapkan status lereng."),
                "reading": (
                    {
                        "value": representative["value"], "unit": representative["unit"],
                        "quantity": representative["quantity"], "depth_cm": None,
                    }
                    if representative is not None else None
                ),
            })
        return {
            "slopes": slopes,
            "status_counts": status_counts,
            "health": {"online": online_total, "offline": offline_total, "total": online_total + offline_total},
        }
