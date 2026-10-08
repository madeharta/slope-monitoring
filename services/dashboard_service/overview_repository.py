"""Dashboard overview aggregation including site severity and device health.

Technical site severity remains independent from operational alarms. Device
connectivity is a telemetry-freshness indicator only; it is not a slope-safety
state. Device map positions come from GNSS-derived records or a surveyed device
reference, never from the generic site coordinate.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from apps.api.config import (
    THRESHOLDS,
    action_for,
    operational_alarm_for,
    operational_alarms_enabled,
    status_for,
    worst,
)

_ONLINE_WINDOW_SECONDS = int(os.getenv("DEVICE_ONLINE_SECONDS", "900"))
_OFFLINE_WINDOW_SECONDS = int(os.getenv("DEVICE_OFFLINE_SECONDS", "3600"))


def _value(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def connectivity_status(last_activity, *, now: datetime | None = None) -> str:
    """Classify device freshness without conflating it with GNSS quality."""
    if last_activity is None:
        return "unknown"
    now = now or datetime.now(timezone.utc)
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)
    age_s = max(0.0, (now - last_activity).total_seconds())
    if age_s <= _ONLINE_WINDOW_SECONDS:
        return "online"
    if age_s <= _OFFLINE_WINDOW_SECONDS:
        return "stale"
    return "offline"


def _latest_time(*values):
    present = [v for v in values if v is not None]
    return max(present) if present else None


class OverviewRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def get_overview(self) -> dict:
        async with self._pool.acquire() as conn:
            sites = await conn.fetch("SELECT site_id, name, lat, lon FROM sites")
            devices = await conn.fetch(
                """
                SELECT
                    d.device_id, d.site_id, d.device_type, d.label, d.last_seen,
                    p.time AS dynamic_position_time,
                    COALESCE(p.latitude, ref.latitude) AS latitude,
                    COALESCE(p.longitude, ref.longitude) AS longitude,
                    COALESCE(p.altitude_m, ref.altitude_m) AS altitude_m,
                    p.gnss_fix_type,
                    p.h_acc_m,
                    CASE
                        WHEN p.time IS NOT NULL THEN p.source_kind
                        WHEN ref.device_id IS NOT NULL THEN 'surveyed_reference'
                        ELSE NULL
                    END AS position_source,
                    COALESCE(p.time, ref.surveyed_at) AS position_time,
                    CASE
                        WHEN p.time IS NOT NULL THEN p.validation_status
                        WHEN ref.device_id IS NOT NULL THEN 'reference'
                        ELSE NULL
                    END AS position_validation_status
                FROM devices d
                LEFT JOIN LATERAL (
                    SELECT q.time, q.latitude, q.longitude, q.altitude_m,
                           q.gnss_fix_type, q.h_acc_m, q.source_kind,
                           q.validation_status
                    FROM (
                        SELECT time, latitude, longitude, altitude_m,
                               gnss_fix_type, h_acc_m,
                               'rtk_direct'::text AS source_kind,
                               validation_status
                        FROM device_position_records
                        WHERE device_id = d.device_id
                        UNION ALL
                        SELECT time, latitude, longitude, ellipsoidal_height_m AS altitude_m,
                               NULL::integer AS gnss_fix_type, h_acc_m,
                               'ppk'::text AS source_kind,
                               validation_status
                        FROM ppk_solution_records
                        WHERE rover_device_id = d.device_id
                          AND quality_gate_status = 'accepted'
                    ) q
                    ORDER BY q.time DESC
                    LIMIT 1
                ) p ON TRUE
                LEFT JOIN device_reference_position ref
                  ON ref.device_id = d.device_id
                ORDER BY d.device_id
                """
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
        operational_ready = operational_alarms_enabled()
        operational_alarm_counts = {"siaga": 0, "bahaya": 0, "total": 0}

        # Backward-compatible aggregate: anything not ONLINE remains in the
        # historical `health.offline` count. `device_health` exposes the new
        # online/stale/offline/unknown breakdown explicitly.
        health_breakdown = {"online": 0, "stale": 0, "offline": 0, "unknown": 0, "total": len(devices)}
        device_items = []
        now = datetime.now(timezone.utc)
        for d in devices:
            last_seen = _value(d, "last_seen")
            dynamic_position_time = _value(d, "dynamic_position_time")
            last_activity = _latest_time(last_seen, dynamic_position_time)
            if last_activity is None and _value(d, "online") is not None:
                # Compatibility for unit-test fixtures and older query shapes.
                state = "online" if bool(_value(d, "online")) else "offline"
            else:
                state = connectivity_status(last_activity, now=now)
            health_breakdown[state] += 1

            lat = _value(d, "latitude")
            lon = _value(d, "longitude")
            position = None
            if lat is not None and lon is not None:
                position = {
                    "lat": lat,
                    "lon": lon,
                    "altitude_m": _value(d, "altitude_m"),
                    "time": _value(d, "position_time").isoformat() if _value(d, "position_time") else None,
                    "source": _value(d, "position_source"),
                    "gnss_fix_type": _value(d, "gnss_fix_type"),
                    "h_acc_m": _value(d, "h_acc_m"),
                    "validation_status": _value(d, "position_validation_status"),
                }
            device_items.append({
                "device_id": d["device_id"],
                "site_id": d["site_id"],
                "device_type": _value(d, "device_type"),
                "label": _value(d, "label"),
                "connectivity_status": state,
                "last_activity": last_activity.isoformat() if last_activity else None,
                "position": position,
            })

        for site_id, site in site_by_id.items():
            site_readings = readings_by_site.get(site_id, [])
            statuses = [status_for(r["quantity"], r["value"]) for r in site_readings]
            site_status = worst(statuses) if statuses else "unknown"
            status_counts[site_status] += 1

            operational_alarm = operational_alarm_for(site_status, enabled=operational_ready)
            if operational_alarm:
                operational_alarm_counts[site_status] += 1
                operational_alarm_counts["total"] += 1

            representative = None
            for r in site_readings:
                if status_for(r["quantity"], r["value"]) == site_status:
                    representative = r
                    break

            slopes.append({
                "site_id": site_id,
                "name": site["name"],
                "lat": site["lat"],
                "lon": site["lon"],
                "status": site_status,
                "technical_status": site_status,
                "validation_status": "validated" if operational_ready else "unvalidated",
                "operational_ready": operational_ready,
                "operational_alarm": operational_alarm,
                "action": action_for(site_status, enabled=operational_ready),
                "reading": (
                    {
                        "value": representative["value"],
                        "unit": representative["unit"],
                        "quantity": representative["quantity"],
                        "depth_cm": None,
                    }
                    if representative is not None else None
                ),
            })

        online_total = health_breakdown["online"]
        non_online_total = health_breakdown["total"] - online_total
        return {
            "slopes": slopes,
            "devices": device_items,
            "status_counts": status_counts,
            "operational_alarm_counts": operational_alarm_counts,
            "validation": {
                "status": "validated" if operational_ready else "unvalidated",
                "operational_ready": operational_ready,
                "gate": "OPERATIONAL_ALARMS_ENABLED",
            },
            "health": {"online": online_total, "offline": non_online_total, "total": health_breakdown["total"]},
            "device_health": health_breakdown,
            "device_health_policy": {
                "online_max_age_s": _ONLINE_WINDOW_SECONDS,
                "offline_min_age_s": _OFFLINE_WINDOW_SECONDS,
            },
        }
