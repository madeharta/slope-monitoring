"""Publish QA RTKLIB relative positions as operational markers (not displacement).

Source: ppk_qa_biznet read-only reader, target: slope_iot restricted writer.
Fail closed for identity/privileges; no reference/baseline/alarm writes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from scripts.publish_gnss_locations import UPSERT

UTC = timezone.utc
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=UTC)
ROVERS = ("ROVER-B1-01", "ROVER-B1-02")


def gps_to_utc(week, tow):
    """Only 2026: verified GPS-UTC=18 s. Reject unsupported years."""
    if not 0 <= float(tow) < 604800 or not 0 <= int(week) < 10000:
        raise ValueError("INVALID_GPS_EPOCH")
    stamp = GPS_EPOCH + timedelta(weeks=int(week), seconds=float(tow) - 18)
    if stamp.year != 2026:
        raise ValueError("GPS_UTC_OFFSET_UNVERIFIED_YEAR")
    return stamp


def operational_row(rover, records, *, minimum_fix=10, minimum_float=20, max_spread_m=10):
    """Build one operational marker from a coherent QA window/source hash.

    Thresholds are provisional *map* eligibility only; never displacement alarms.
    """
    if rover not in ROVERS:
        raise ValueError("UNKNOWN_ROVER")
    parsed = []
    for r in records:
        quality = int(r["rtklib_quality"])
        if quality not in (1, 2) or int(r["satellite_count"]) < 6:
            continue
        lat, lon, height = (float(r[k]) for k in ("latitude_deg", "longitude_deg", "ellipsoidal_height_m"))
        if not all(map(math.isfinite, (lat, lon, height))) or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        stamp = gps_to_utc(r["gps_week"], r["gps_tow_s"])
        parsed.append((stamp, lat, lon, height, quality, int(r["satellite_count"])))
    fixes = [r for r in parsed if r[4] == 1]
    floats = [r for r in parsed if r[4] == 2]
    if len(fixes) >= minimum_fix:
        chosen, quality, status = fixes, 1, "ACCEPTED_PPK_FIX"
    elif len(floats) >= minimum_float:
        chosen, quality, status = floats, 2, "ACCEPTED_PPK_FLOAT"
    else:
        raise ValueError("INSUFFICIENT_PPK_MAP_SOLUTIONS")
    lat = median(p[1] for p in chosen)
    lon = median(p[2] for p in chosen)
    h = median(p[3] for p in chosen)
    spread = max(math.hypot((p[1]-lat)*111320, (p[2]-lon)*111320*math.cos(math.radians(lat))) for p in chosen)
    if spread > max_spread_m or not math.isfinite(spread):
        raise ValueError("UNSTABLE_PPK_MAP_POSITION")
    timestamp = max(p[0] for p in chosen)
    return (rover, lat, lon, h, timestamp, "RTKLIB_PPK", quality,
            status, len(chosen), round(spread, 3),
            {"min_satellites": min(p[5] for p in chosen),
             "fix_epochs": len(fixes), "float_epochs": len(floats),
             "vertical_datum": "ELLIPSOIDAL_WGS84",
             "use": "OPERATIVE_MARKER_ONLY_NOT_DISPLACEMENT"})


def recent_candidates(rows, now, max_age_hours=48):
    """Select newest eligible coherent window per rover; do not mix PPK runs."""
    bins = defaultdict(list)
    for r in rows:
        rover = r["rover_device_id"]
        if rover not in ROVERS or not r.get("source_pos_sha256"):
            continue
        try:
            stamp = gps_to_utc(r["gps_week"], r["gps_tow_s"])
        except (ValueError, TypeError, OverflowError):
            continue
        if stamp > now or now - stamp > timedelta(hours=max_age_hours):
            continue
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        bins[(rover, hour, r["source_pos_sha256"])].append(r)
    candidates = []
    for (rover, _, fingerprint), batch in bins.items():
        try:
            result = operational_row(rover, batch)
        except (ValueError, TypeError, KeyError):
            continue
        result[-1]["source_pos_sha256"] = fingerprint
        candidates.append(result)
    latest = {}
    for row in candidates:
        if row[0] not in latest or row[4] > latest[row[0]][4]:
            latest[row[0]] = row
    return [latest[k] for k in sorted(latest)]


def _check_connection(conn, expected_db, expected_role, table, write=False):
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        if cur.fetchone() != (expected_db, expected_role):
            raise RuntimeError("DB_IDENTITY_MISMATCH")
        # PostgreSQL comma-separated has_table_privilege checks ANY permission,
        # not ALL. Check each required permission separately.
        required = ("SELECT", "INSERT", "UPDATE") if write else ("SELECT",)
        for privilege in required:
            cur.execute("SELECT has_table_privilege(current_user, %s, %s)",
                        (table, privilege))
            if cur.fetchone()[0] is not True:
                raise RuntimeError("DB_PRIVILEGE_MISSING: " + privilege)
        forbidden = ("DELETE",) if write else ("INSERT", "UPDATE", "DELETE")
        for privilege in forbidden:
            cur.execute("SELECT has_table_privilege(current_user, %s, %s)",
                        (table, privilege))
            if cur.fetchone()[0] is True:
                raise RuntimeError("DB_EXCESS_PRIVILEGE: " + privilege)


def run(args):
    import psycopg
    from psycopg.rows import dict_row
    qa_dsn = os.getenv("MAGRIS_GNSS_QA_READER_DSN")
    writer_dsn = os.getenv("MAGRIS_GNSS_LOCATION_WRITER_DSN")
    if not qa_dsn:
        raise RuntimeError("QA_READER_DSN_MISSING")
    if args.apply and (not writer_dsn or qa_dsn == writer_dsn):
        raise RuntimeError("SEPARATE_LOCATION_WRITER_DSN_REQUIRED")
    qa_db = os.getenv("MAGRIS_GNSS_QA_READER_DB", "ppk_qa_biznet")
    qa_role = os.getenv("MAGRIS_GNSS_QA_READER_ROLE", "ppk_qa_reader")
    now = datetime.now(UTC)
    with psycopg.connect(qa_dsn, row_factory=dict_row, options="-c default_transaction_read_only=on") as conn:
        _check_connection(conn, qa_db, qa_role, "public.ppk_qa_experimental_solutions")
        with conn.cursor() as cur:
            # Only relative FIX/FLOAT observations are eligible for PPK markers.
            # Limit per rover (not globally) to prevent a busy rover starving the
            # other rover. SPP fallback is published independently by scheduler.
            cur.execute("""WITH eligible AS (
                       SELECT rover_device_id, gps_week, gps_tow_s,
                              rtklib_quality, satellite_count,
                              latitude_deg, longitude_deg, ellipsoidal_height_m,
                              source_pos_sha256,
                              ROW_NUMBER() OVER (
                                  PARTITION BY rover_device_id
                                  ORDER BY gps_week DESC, gps_tow_s DESC
                              ) AS device_row
                       FROM public.ppk_qa_experimental_solutions
                       WHERE rover_device_id IN ('ROVER-B1-01', 'ROVER-B1-02')
                         AND rtklib_quality IN (1, 2)
                         AND satellite_count >= 6
                   )
                   SELECT rover_device_id, gps_week, gps_tow_s, rtklib_quality,
                          satellite_count, latitude_deg, longitude_deg,
                          ellipsoidal_height_m, source_pos_sha256
                   FROM eligible WHERE device_row <= 5000
                   ORDER BY rover_device_id, gps_week DESC, gps_tow_s DESC""")
            rows = cur.fetchall()
    candidates = recent_candidates(rows, now, args.max_age_hours)
    if not args.apply:
        return {"mode": "DRY_RUN", "candidate_devices": [r[0] for r in candidates]}
    if not candidates:
        return {"mode": "NO_ELIGIBLE_NEW_PPK", "device_ids": []}
    db = os.getenv("MAGRIS_GNSS_LOCATION_WRITER_DB", "slope_iot")
    role = os.getenv("MAGRIS_GNSS_LOCATION_WRITER_ROLE")
    if not role:
        raise RuntimeError("LOCATION_WRITER_ROLE_REQUIRED")
    with psycopg.connect(writer_dsn) as conn:
        _check_connection(conn, db, role, "public.gnss_device_operational_locations", write=True)
        with conn.transaction():
            for r in candidates:
                conn.execute(UPSERT, (*r[:-1], json.dumps(r[-1])))
    return {"mode": "APPLIED", "device_ids": [r[0] for r in candidates]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-age-hours", type=int, default=48, choices=range(1, 169))
    args = parser.parse_args()
    print(json.dumps(run(args), sort_keys=True))


if __name__ == "__main__":
    main()
