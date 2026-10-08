"""Backs `GET /api/overview` — item #6, the dashboard-read API that was
missing entirely until now (see PROJECT_AUDIT_LOG.md, several entries
flagging this as the single biggest blocker to the frontend showing real
data). Response shape is reverse-engineered EXACTLY from
apps/frontend/src/pages/Overview.jsx and components/SiteMap.jsx — not
guessed: `slopes[].{site_id,name,lat,lon,status,action,reading}`,
`status_counts.{normal,siaga,bahaya}`, `health.{online,offline,total}`.

Status computed via the EXISTING `apps/api/config.py::status_for()` +
`THRESHOLDS` — that module already existed (built earlier, unused until
now) and is reused verbatim, not reimplemented.
"""

from __future__ import annotations

from apps.api.config import (
    THRESHOLDS,
    action_for,
    operational_alarm_for,
    operational_alarms_enabled,
    status_for,
    worst,
)

# A device is "online" if it uploaded within this window — 3x the
# documented periodic_upload_s default (300s, see device_config.py) gives
# slack for one missed cycle before flagging offline, without waiting so
# long that a genuinely dead device still shows green.
_ONLINE_WINDOW_SECONDS = 900


class OverviewRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def get_overview(self) -> dict:
        async with self._pool.acquire() as conn:
            sites = await conn.fetch("SELECT site_id, name, lat, lon FROM sites")
            devices = await conn.fetch(
                # BUG FIX (2026-09-19, confirmed via real 500 error, Content-
                # Length 70 = the generic INTERNAL_ERROR envelope): `$1 || '
                # seconds'` tried to concatenate an INTEGER parameter with
                # TEXT using `||` — Postgres has no `integer || text`
                # operator (asyncpg sends $1 pre-typed as int4/int8, not
                # left untyped for Postgres to infer as text). Fixed with
                # make_interval(), the correct way to build an interval
                # from a numeric parameter — no casting/concatenation at all.
                "SELECT device_id, site_id, "
                "(last_seen IS NOT NULL AND last_seen > now() - make_interval(secs => $1)) AS online "
                "FROM devices",
                _ONLINE_WINDOW_SECONDS,
            )
            # Latest reading per (device_id, quantity), restricted to
            # quantities that actually drive status (THRESHOLDS keys) —
            # no point pulling ppa/ppv/etc here, they never change `status`.
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

        # Operational response is a separate safety domain from technical
        # threshold severity. Default is fail-closed.
        operational_ready = operational_alarms_enabled()
        operational_alarm_counts = {"siaga": 0, "bahaya": 0, "total": 0}

        online_total = offline_total = 0

        for site_id, site in site_by_id.items():
            site_readings = readings_by_site.get(site_id, [])
            statuses = [status_for(r["quantity"], r["value"]) for r in site_readings]
            site_status = worst(statuses) if statuses else "unknown"
            status_counts[site_status] += 1

            operational_alarm = operational_alarm_for(
                site_status,
                enabled=operational_ready,
            )
            if operational_alarm:
                operational_alarm_counts[site_status] += 1
                operational_alarm_counts["total"] += 1

            # "reading" shown on the alert card: the one driving the worst
            # status (tie-broken by most recent — `time` is already sorted
            # DESC per device+quantity, so a stable pick is the first match).
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
                # `status` is retained for backward compatibility and is
                # technical severity, not an operational decision.
                "status": site_status,
                "technical_status": site_status,
                "validation_status": "validated" if operational_ready else "unvalidated",
                "operational_ready": operational_ready,
                "operational_alarm": operational_alarm,
                "action": action_for(site_status, enabled=operational_ready),
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
            "operational_alarm_counts": operational_alarm_counts,
            "validation": {
                "status": "validated" if operational_ready else "unvalidated",
                "operational_ready": operational_ready,
                "gate": "OPERATIONAL_ALARMS_ENABLED",
            },
            "health": {"online": online_total, "offline": offline_total, "total": online_total + offline_total},
        }
