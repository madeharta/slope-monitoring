"""Opt-in, one-pass PPK QA worker. Never writes operational PPK/displacement tables.

Requires manually reviewed QA-only ledger migration, see sql/013_ppk_qa_jobs.sql.
The existing 23-column QA solutions table is preserved unchanged.
This is a candidate implementation, not field/geodetic acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
GPS_UTC_LEAP_SECONDS_2026 = 18  # for the explicitly scoped 2026 historic QA data


def gps_epoch_2026(value: datetime) -> tuple[int, float]:
    if value.tzinfo is None:
        raise ValueError("GNSS solution timestamp must be timezone-aware")
    utc = value.astimezone(timezone.utc)
    if not (datetime(2026, 1, 1, tzinfo=timezone.utc) <= utc < datetime(2027, 1, 1, tzinfo=timezone.utc)):
        raise ValueError("worker GPS-UTC offset is only verified for 2026")
    total = (utc - GPS_EPOCH).total_seconds() + GPS_UTC_LEAP_SECONDS_2026
    return int(total // 604800), round(total % 604800, 6)


def fingerprint(base: bytes, rover: bytes, nav: bytes, config: bytes, reference: tuple[float, float, float], scope: str = "") -> str:
    sha = hashlib.sha256(b"MAGRIS_PPK_QA_WORKER_V1\x00")
    for part in (base, rover, nav, config, repr(reference).encode(), scope.encode()):
        sha.update(len(part).to_bytes(8, "big"))
        sha.update(part)
    return sha.hexdigest()


def join_rawx(rows: list[dict]) -> bytes:
    frames = []
    for row in rows:
        try:
            frame = base64.b64decode(row["raw_payload_base64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid RAWX base64; window quarantined") from exc
        # Each source row is a single UBX message with valid frame boundaries.
        if len(frame) < 8 or frame[:2] != b"\xb5\x62":
            raise ValueError("invalid UBX sync or incomplete frame")
        declared = int.from_bytes(frame[4:6], "little")
        if len(frame) != declared + 8:
            raise ValueError("UBX message length mismatch")
        a = b = 0
        for byte in frame[2:-2]:
            a = (a + byte) & 255
            b = (b + a) & 255
        if frame[-2:] != bytes((a, b)):
            raise ValueError("UBX checksum mismatch")
        if frame[2:4] != b"\x02\x15":
            raise ValueError("not UBX-RXM-RAWX")
        frames.append(frame)
    return b"".join(frames)

def rawx_measurement_count(row: dict) -> int:
    """Read RXM-RAWX numMeas after full frame validation."""
    frame = join_rawx([row])

    if len(frame) < 24:
        raise ValueError("RAWX header incomplete")

    payload_length = int.from_bytes(frame[4:6], "little")
    num_meas = frame[17]

    if payload_length != 16 + 32 * num_meas:
        raise ValueError("RAWX measurement payload length mismatch")

    return num_meas

@dataclass(frozen=True)
class Scope:
    site_id: str
    base_id: str
    rover_id: str
    base_reference: tuple[float, float, float]
    nav_file: Path
    rtklib_config: Path


def verify_forward_qa_config(raw: bytes) -> None:
    """Reject ambiguity of incremental solver mode and non-QA references."""
    options = {}
    for line in raw.decode("utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = (v.strip() for v in line.split("=", 1))
        if key in options:
            raise ValueError(f"duplicate RTKLIB setting: {key}")
        options[key] = value
    for key, expected in {"pos1-posmode": "kinematic", "pos1-soltype": "forward", "ant2-postype": "llh"}.items():
        if options.get(key) != expected:
            raise ValueError(f"QA worker requires {key}={expected}")
    for key in ("ant2-pos1", "ant2-pos2", "ant2-pos3"):
        if key not in options:
            raise ValueError(f"QA worker requires {key}")


def verify_base_coordinates_in_config(raw: bytes, reference: tuple[float, float, float]) -> None:
    values = {}
    for line in raw.decode("utf-8").splitlines():
        line = line.split("#", 1)[0]
        if "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    for key, expected in zip(("ant2-pos1", "ant2-pos2", "ant2-pos3"), reference):
        try:
            observed = float(values[key])
        except (ValueError, KeyError):
            raise ValueError(f"invalid reference in {key}")
        if not __import__("math").isfinite(observed) or abs(observed - expected) > 1e-8:
            raise ValueError(f"reference mismatch: {key}")


def verify_scope(s: Scope) -> None:
    if not s.site_id or not s.base_id or not s.rover_id or s.base_id == s.rover_id:
        raise ValueError("distinct site/base/rover IDs required")
    if any(not (-90 <= x <= 90 if i == 0 else -180 <= x <= 180 if i == 1 else -15000 <= x <= 15000) for i, x in enumerate(s.base_reference)):
        raise ValueError("invalid provisional reference")
    for file in (s.nav_file, s.rtklib_config):
        if not file.is_file() or not file.stat().st_size:
            raise ValueError(f"missing/empty supporting file {file}")


def stale_running_lease(updated_at: datetime | None, now: datetime, ttl_seconds: int = 1800) -> bool:
    """Fail-closed recovery gate. Call only while holding the session advisory lock."""
    if updated_at is None or updated_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("missing or naive job lease timestamp")
    age = (now.astimezone(timezone.utc) - updated_at.astimezone(timezone.utc)).total_seconds()
    if age < 0:
        raise ValueError("job lease timestamp is in the future")
    return age >= ttl_seconds


async def run_once(args):
    import asyncpg
    from ml.pipeline.preprocessing.ppk_engine import RTKLibPPKEngine

    s = Scope(args.site, args.base, args.rover, (args.base_lat, args.base_lon, args.base_alt),
              Path(args.nav), Path(args.config))
    verify_scope(s)
    if args.apply and os.getenv("PPK_QA_AUTOMATION_ENABLED", "false").lower() != "true":
        raise RuntimeError("worker DISABLED; set PPK_QA_AUTOMATION_ENABLED=true explicitly")
    source_dsn = os.getenv("PPK_QA_SOURCE_DATABASE_URL")
    qa_dsn = os.getenv("PPK_QA_WRITER_DATABASE_URL")
    expected_source_db = os.getenv("PPK_QA_SOURCE_DB_NAME")
    expected_qa_db = os.getenv("PPK_QA_WRITER_DB_NAME")
    expected_source_role = os.getenv("PPK_QA_SOURCE_DB_ROLE")
    expected_qa_role = os.getenv("PPK_QA_WRITER_DB_ROLE")
    if not all((source_dsn, qa_dsn, expected_source_db, expected_qa_db,
                expected_source_role, expected_qa_role)):
        raise RuntimeError("dual-DB connection and identity configuration required")
    if source_dsn == qa_dsn or expected_source_db == expected_qa_db:
        raise RuntimeError("SOURCE and QA WRITER must use separate databases")
    if expected_source_role == expected_qa_role:
        raise RuntimeError("SOURCE and QA WRITER must use separate roles")
    start = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    end = datetime.fromisoformat(args.until.replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("since/until must include UTC offset")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if end <= start or end - start > timedelta(days=7):
        raise ValueError("window range must be >0 and <=7 days")
    nav_bytes = s.nav_file.read_bytes()
    config_bytes = s.rtklib_config.read_bytes()
    verify_forward_qa_config(config_bytes)
    verify_base_coordinates_in_config(config_bytes, s.base_reference)
    source_conn = await asyncpg.connect(source_dsn)
    try:
        conn = await asyncpg.connect(qa_dsn)
    except Exception:
        await source_conn.close()
        raise

    failures = 0
    try:
        source_identity = await source_conn.fetchrow(
            "SELECT current_database() AS db, current_user AS role"
        )
        qa_identity = await conn.fetchrow(
            "SELECT current_database() AS db, current_user AS role"
        )
        if (source_identity["db"] != expected_source_db
                or source_identity["role"] != expected_source_role
                or qa_identity["db"] != expected_qa_db
                or qa_identity["role"] != expected_qa_role):
            raise RuntimeError("database identity mismatch; fail closed")

        await source_conn.execute("SET default_transaction_read_only = on")

        source_ok = await source_conn.fetchval("""
            SELECT has_table_privilege(current_user,
                       'public.gnss_raw_samples', 'SELECT')
               AND has_table_privilege(current_user,
                       'public.devices', 'SELECT')
        """)
        source_write = await source_conn.fetchval("""
            SELECT has_table_privilege(current_user,
                       'public.gnss_raw_samples', 'INSERT,UPDATE,DELETE')
                OR has_table_privilege(current_user,
                       'public.devices', 'INSERT,UPDATE,DELETE')
        """)
        if not source_ok or source_write:
            raise RuntimeError("SOURCE role privileges invalid")

        if args.apply:
            writer_ok = await conn.fetchval("""
                SELECT has_table_privilege(current_user,
                           'public.ppk_qa_jobs', 'SELECT,INSERT,UPDATE')
                   AND has_table_privilege(current_user,
                           'public.ppk_qa_experimental_solutions',
                           'SELECT,INSERT,UPDATE')
            """)
            if not writer_ok:
                raise RuntimeError("QA writer privileges insufficient")
            exists = await conn.fetchval("SELECT to_regclass('public.ppk_qa_experimental_solutions') IS NOT NULL AND to_regclass('public.ppk_qa_jobs') IS NOT NULL")
            if not exists:
                raise RuntimeError("QA-only tables missing; worker will not create them automatically")
            actual = {r["column_name"] for r in await conn.fetch("""SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='ppk_qa_experimental_solutions'""")}
            required = {"source_pos_sha256", "site_id", "base_device_id", "rover_device_id", "gps_week", "gps_tow_s", "latitude_deg", "longitude_deg", "ellipsoidal_height_m", "rtklib_quality", "satellite_count", "sdn_m", "sde_m", "sdu_m", "age_s", "ratio", "reference_type", "validation_status", "schema_version"}
            if not required <= actual:
                raise RuntimeError("QA schema contract mismatch: missing " + repr(sorted(required-actual)))
        cursor = start
        total_jobs = 0
        total_epochs = 0
        while cursor < end:
            stop = min(cursor + timedelta(minutes=args.window_minutes), end)
            # Both devices and the site must be known. We select via devices to avoid cross-site mixing.
            records = await source_conn.fetch("""
                SELECT s.time,s.device_id,s.raw_payload_base64
                FROM gnss_raw_samples s
                JOIN devices d ON d.device_id=s.device_id
                WHERE d.site_id=$1 AND s.device_id=ANY($2::text[])
                  AND s.time >= $3 AND s.time < $4
                ORDER BY s.time,s.device_id
            """, s.site_id, [s.base_id, s.rover_id], cursor, stop)
            base = [dict(r) for r in records if r['device_id'] == s.base_id]
            rover = [dict(r) for r in records if r['device_id'] == s.rover_id]
            if not base or not rover:
                print(json.dumps({'window': cursor.isoformat(), 'status': 'WAITING_PAIR', 'base':len(base),'rover':len(rover)}))
                cursor = stop
                continue
            # Fail closed on malformed RAWX before applying eligibility filters.
            join_rawx(base)
            join_rawx(rover)

            usable_base = [r for r in base if rawx_measurement_count(r) > 0]
            usable_rover = [r for r in rover if rawx_measurement_count(r) > 0]

            if not usable_base:
                print(json.dumps({
                    "window": cursor.isoformat(),
                    "status": "WAITING_PAIR",
                    "reason_code": "BASE_RAWX_ZERO_MEASUREMENTS",
                    "base_total": len(base),
                    "base_usable": 0,
                }))
                cursor = stop
                continue

            if not usable_rover:
                print(json.dumps({
                    "window": cursor.isoformat(),
                    "status": "WAITING_PAIR",
                    "reason_code": "ROVER_RAWX_ZERO_MEASUREMENTS",
                    "rover_total": len(rover),
                    "rover_usable": 0,
                }))
                cursor = stop
                continue

            base = usable_base
            rover = usable_rover

            rover_overlap = sum(any(abs((r['time']-b['time']).total_seconds()) <= 2 for b in base) for r in rover)
            if rover_overlap < args.min_matched:
                print(json.dumps({'window': cursor.isoformat(), 'status': 'INSUFFICIENT_OVERLAP','matched':rover_overlap}))
                cursor = stop
                continue
            base_raw = join_rawx(base)
            rover_raw = join_rawx(rover)
            key = fingerprint(base_raw, rover_raw, nav_bytes, config_bytes, s.base_reference, f"{s.site_id}|{s.base_id}|{s.rover_id}|{cursor.isoformat()}|{stop.isoformat()}")
            if not args.apply:
                print(json.dumps({'window':cursor.isoformat(), 'status':'DRY_RUN_ELIGIBLE','matched':rover_overlap,'fingerprint':key}))
                total_jobs += 1
                cursor = stop
                continue
            # Session advisory lock prevents parallel cron instances; released on connection close.
            if not await conn.fetchval("SELECT pg_try_advisory_lock(hashtext('magris.ppk.qa.worker'))"):
                raise RuntimeError('another PPK QA worker holds the lock')
            try:
                previous = await conn.fetchrow("""SELECT status, updated_at, attempts FROM public.ppk_qa_jobs
                     WHERE site_id=$1 AND rover_device_id=$2 AND window_start_utc=$3 AND input_fingerprint=$4""",
                     s.site_id,s.rover_id,cursor,key)
                if previous and previous['status'] == 'COMPLETED':
                    print(json.dumps({'window':cursor.isoformat(),'status':'SKIPPED_ALREADY_COMPLETED'}))
                    cursor = stop
                    continue
                # A session lock alone does not prove a RUNNING job belongs to a live worker.
                # Only reclaim it after the lease expires; recent RUNNING blocks fail closed.
                if previous and previous['status'] == 'RUNNING':
                    try:
                        expired = stale_running_lease(previous['updated_at'], datetime.now(timezone.utc))
                    except ValueError as exc:
                        raise RuntimeError('RUNNING job lease invalid; manual review') from exc
                    if not expired:
                        raise RuntimeError('RUNNING job lease is still active; stop rather than steal')
                    print(json.dumps({'window':cursor.isoformat(),'status':'RECOVER_STALE_RUNNING',
                                      'prior_attempts':previous['attempts']}))
                await conn.execute("""INSERT INTO public.ppk_qa_jobs
                    (site_id,rover_device_id,window_start_utc,input_fingerprint,status,attempts)
                    VALUES ($1,$2,$3,$4,'RUNNING',1)
                    ON CONFLICT (site_id,rover_device_id,window_start_utc,input_fingerprint)
                    DO UPDATE SET status='RUNNING',attempts=public.ppk_qa_jobs.attempts+1,updated_at=now(),last_error=NULL""",
                    s.site_id,s.rover_id,cursor,key)
                try:
                    engine = RTKLibPPKEngine(*s.base_reference,nav_file=str(s.nav_file),
                                            rtklib_config_file=str(s.rtklib_config))
                    result = await asyncio.to_thread(engine.solve_window,base_raw,rover_raw,observed_at=cursor)
                    if not result.solutions:
                        raise RuntimeError('RTKLIB generated zero solutions')
                    values=[]
                    for sol in result.solutions:
                        if not cursor <= sol.timestamp_utc.astimezone(timezone.utc) < stop:
                            continue
                        week,tow = gps_epoch_2026(sol.timestamp_utc)
                        values.append((result.solution_pos_sha256,s.site_id,s.base_id,s.rover_id,week,tow,
                            sol.latitude,sol.longitude,sol.ellipsoidal_height_m,sol.rtklib_quality,sol.satellites,
                            sol.sdn_m,sol.sde_m,sol.sdu_m,sol.age_s,sol.ratio,
                            'PROVISIONAL_SPP','unvalidated','ppk.qa.solution.v1'))
                    if not values:
                        raise RuntimeError('RTKLIB solutions outside requested UTC window')
                    epoch_keys = [(v[4], v[5]) for v in values]
                    if len(epoch_keys) != len(set(epoch_keys)):
                        raise RuntimeError('duplicate GNSS epochs produced by RTKLIB')
                    if not result.solution_pos_sha256 or len(result.solution_pos_sha256) != 64:
                        raise RuntimeError('RTKLIB output provenance SHA-256 missing')
                    async with conn.transaction():
                        # Never overwrite existing QA epochs, particularly the 201 historical fixtures.
                        # Serialize with QA worker advisory lock and use anti-join because the legacy
                        # table's uniqueness constraints have not been established by this report.
                        for v in values:
                            existing_rows = await conn.fetch("""SELECT source_pos_sha256,base_device_id,
                                latitude_deg,longitude_deg,ellipsoidal_height_m,rtklib_quality,satellite_count,
                                sdn_m,sde_m,sdu_m,age_s,ratio,reference_type,validation_status,schema_version
                                FROM public.ppk_qa_experimental_solutions
                                WHERE site_id=$1 AND rover_device_id=$2 AND gps_week=$3 AND gps_tow_s=$4""",
                                v[1],v[3],v[4],v[5])
                            if len(existing_rows) > 1:
                                raise RuntimeError('duplicate historical QA epoch; manual review required')
                            if existing_rows:
                                old_record = existing_rows[0]
                                old_values = tuple(old_record[k] for k in (
                                    'source_pos_sha256','base_device_id','latitude_deg','longitude_deg',
                                    'ellipsoidal_height_m','rtklib_quality','satellite_count','sdn_m','sde_m',
                                    'sdu_m','age_s','ratio','reference_type','validation_status','schema_version'))
                                new_values = (v[0],v[2],*v[6:])
                                if old_values != new_values:
                                    raise RuntimeError('QA epoch collision with different content; manual review required')
                            await conn.execute("""INSERT INTO public.ppk_qa_experimental_solutions
                                (source_pos_sha256,site_id,base_device_id,rover_device_id,gps_week,gps_tow_s,
                                 latitude_deg,longitude_deg,ellipsoidal_height_m,rtklib_quality,satellite_count,
                                 sdn_m,sde_m,sdu_m,age_s,ratio,reference_type,validation_status,schema_version)
                                SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19
                                WHERE NOT EXISTS (
                                  SELECT 1 FROM public.ppk_qa_experimental_solutions
                                  WHERE site_id=$2 AND rover_device_id=$4 AND gps_week=$5 AND gps_tow_s=$6
                                )""", *v)
                        await conn.execute("""UPDATE public.ppk_qa_jobs SET status='COMPLETED',
                            solution_count=$5, updated_at=now() WHERE site_id=$1 AND rover_device_id=$2
                            AND window_start_utc=$3 AND input_fingerprint=$4""",
                            s.site_id,s.rover_id,cursor,key,len(values))
                    print(json.dumps({'window':cursor.isoformat(),'status':'COMPLETED','solutions':len(values)}))
                    total_epochs+=len(values)
                except Exception as exc:
                    await conn.execute("""UPDATE public.ppk_qa_jobs SET status='FAILED',
                        last_error=$5,updated_at=now() WHERE site_id=$1 AND rover_device_id=$2
                        AND window_start_utc=$3 AND input_fingerprint=$4""",
                        s.site_id,s.rover_id,cursor,key,str(exc)[:1000])
                    failures += 1
                    print(json.dumps({'window':cursor.isoformat(),'status':'FAILED','error':str(exc)[:300]}))
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtext('magris.ppk.qa.worker'))")
            cursor=stop
        print(json.dumps({'eligible_windows':total_jobs,'persisted_epochs':total_epochs,'apply':args.apply,'failures':failures}))
        if failures:
            raise RuntimeError(f'{failures} PPK QA job(s) FAILED; nonzero exit for scheduler')
    finally:
        try:
            await conn.close()
        finally:
            await source_conn.close()


def main():
    parser=argparse.ArgumentParser(description='MAGRIS PPK experimental QA worker; default dry run')
    parser.add_argument('--site',default='ITB-STAGING-01')
    parser.add_argument('--base',default='BASE-01')
    parser.add_argument('--rover',default='ROVER-B1-02')
    parser.add_argument('--base-lat',type=float,required=True)
    parser.add_argument('--base-lon',type=float,required=True)
    parser.add_argument('--base-alt',type=float,required=True)
    parser.add_argument('--nav',required=True)
    parser.add_argument('--config',default='config/rtklib_ppk.conf')
    parser.add_argument('--since',required=True)
    parser.add_argument('--until',required=True)
    parser.add_argument('--window-minutes',type=int,default=5,choices=(5,10,15,30,60))
    parser.add_argument('--min-matched',type=int,default=4)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    asyncio.run(run_once(args))

if __name__=='__main__':
    main()
