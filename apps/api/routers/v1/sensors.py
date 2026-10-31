from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request

from apps.api.dependencies import get_db_pool, require_role
from common.security import TokenPayload
from services.monitoring_service.sensor_read_repository import (
    DEFAULT_MAX_POINTS, HARD_MAX_POINTS, SensorReadRepository,
)

router = APIRouter(prefix="/api/v1/sensors", tags=["sensors"])


def _iso(value):
    return value.isoformat() if value is not None else None


@router.get("/gnss")
async def get_gnss_series(
    request: Request,
    site_id: str,
    device_id: str | None = None,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=2000, ge=1, le=HARD_MAX_POINTS),
    max_points: int | None = Query(default=None, ge=2, le=HARD_MAX_POINTS),
    gnss_fix_type: int | None = Query(default=None),
    validation_status: str | None = Query(default=None),
    user: TokenPayload = Depends(require_role("viewer")),
) -> dict:
    if from_time and to_time and from_time >= to_time:
        from common.errors import AppError, ErrorCode
        raise AppError(ErrorCode.VALIDATION_ERROR, "from must be earlier than to")

    repository = SensorReadRepository(get_db_pool(request))
    window = None

    if max_points is not None:
        window = await repository.get_gnss_window(
            site_id=site_id,
            device_id=device_id,
            from_time=from_time,
            to_time=to_time,
            max_points=max_points,
            gnss_fix_type=gnss_fix_type,
            validation_status=validation_status,
        )
        rows = window["rows"]
    else:
        rows = await repository.list_gnss(
            site_id=site_id,
            device_id=device_id,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
        )

    return {
        "schema_version": "sensor.gnss.v1",
        "source": "actual",
        "interpolation": "none",
        "validation_status": "unvalidated",
        "site_id": site_id,
        "device_id": device_id,
        "requested_window": {
            "from": _iso(from_time),
            "to": _iso(to_time),
        },
        "window_summary": ({
            "total_rows": window["total_rows"],
            "returned_rows": window["returned_rows"],
            "raw_first_timestamp": _iso(window["first_time"]),
            "raw_last_timestamp": _iso(window["last_time"]),
            "median_h_acc_m": window["median_h_acc_m"],
            "median_gap_ms": window["median_gap_ms"],
            "max_gap_ms": window["max_gap_ms"],
            "downsampling": {
                "method": "none" if window["stride"] == 1 else "deterministic_stride",
                "stride": window["stride"],
                "display_only": True,
                "note": "Raw persisted GNSS rows remain authoritative for continuity statistics.",
            },
        } if window is not None else None),
        "rows": [{
            "timestamp_utc": _iso(r["time"]),
            "device_id": r["device_id"], "site_id": r["site_id"],
            "latitude": r["latitude"], "longitude": r["longitude"],
            "altitude_m": r["altitude_m"],
            "gnss_fix_type": r["gnss_fix_type"], "h_acc_m": r["h_acc_m"],
            "source_kind": r["source_kind"],
            "validation_status": r["validation_status"],
            "source_file": r["source_file"],
            "upload_origin": r["upload_origin"],
            "source_received_at": _iso(r["source_received_at"]),
        } for r in rows],
    }




# BATCH12_RAWX_OBSERVATIONS_V1
# BATCH12_CANONICAL_RAWX_V2

# BATCH12_GNSS_SYNC_QA_V1: observational time matching, NOT PPK acceptance.
@router.get("/gnss/rawx/synchronization")
async def get_rawx_synchronization(
    request: Request,
    site_id: str,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    tolerance_s: float = Query(default=2.0, gt=0, le=2.0),
    user: TokenPayload = Depends(require_role("viewer")),
) -> dict:
    import base64, binascii
    from bisect import bisect_left
    from collections import defaultdict
    from datetime import timedelta, timezone
    from fastapi import HTTPException
    from ml.pipeline.preprocessing.gnss_rawx_time import canonical_rawx_utc

    if any(t is not None and t.tzinfo is None for t in (from_time, to_time)):
        raise HTTPException(status_code=422, detail="timezone-aware UTC window required")
    end = to_time or datetime.now(timezone.utc)
    start = from_time or (end - timedelta(days=7))
    if start >= end or end - start > timedelta(days=31):
        raise HTTPException(status_code=422, detail="window must be positive and at most 31 days")
    async with get_db_pool(request).acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.device_id, r.time, r.raw_payload_base64
            FROM gnss_raw_samples r JOIN devices d ON d.device_id = r.device_id
            WHERE d.site_id = $1 AND r.time >= $2 AND r.time <= $3
            ORDER BY r.time, r.device_id LIMIT 20001
        """, site_id, start - timedelta(hours=8), end + timedelta(hours=8))
    if len(rows) > 20000:
        raise HTTPException(status_code=422, detail="Too many epochs; narrow the window")
    by_device = defaultdict(set)
    invalid = 0
    for row in rows:
        try:
            observed = canonical_rawx_utc(base64.b64decode(row["raw_payload_base64"], validate=True), row["time"])
        except (ValueError, TypeError, binascii.Error):
            invalid += 1
            continue
        if start <= observed <= end:
            by_device[row["device_id"]].add(observed)
    base = sorted(by_device.get("BASE-01", set()))
    rovers = []
    for device in sorted(k for k in by_device if k.startswith("ROVER-") and k != "ROVER-01"):
        epochs = sorted(by_device[device]); match = 0; nearest_s = None
        for observed in epochs:
            i = bisect_left(base, observed)
            choices = [abs((base[j] - observed).total_seconds()) for j in (i - 1, i) if 0 <= j < len(base)]
            if choices:
                distance = min(choices)
                nearest_s = distance if nearest_s is None else min(nearest_s, distance)
                if distance <= tolerance_s: match += 1
        rovers.append({"device_id": device, "rover_epochs": len(epochs), "matched_epochs": match,
                       "unmatched_epochs": len(epochs) - match, "nearest_offset_s": nearest_s})
    return {"schema_version": "sensor.gnss.rawx.synchronization.qa.v1", "source": "actual",
            "site_id": site_id, "time_basis": "verified_ubx_rxm_rawx_utc",
            "requested_window": {"from": start.isoformat(), "to": end.isoformat()},
            "base_id": "BASE-01", "base_epochs": len(base), "tolerance_s": tolerance_s,
            "rovers": rovers, "invalid_time_candidates": invalid, "validation_status": "experimental",
            "interpretation": "Nearest GNSS epoch timing only; not common-satellite or PPK solution validation."}

# BATCH12_RAWX_SATELLITE_QUALITY_V1 - authenticated read-only QA metrics.
@router.get("/gnss/rawx/satellite-quality")
async def get_rawx_satellite_quality(
    request: Request,
    site_id: str,
    device_id: str,
    from_time: datetime = Query(alias="from"),
    to_time: datetime = Query(alias="to"),
    user: TokenPayload = Depends(require_role("viewer")),
) -> dict:
    import base64, binascii, math, struct
    from collections import Counter
    from datetime import timedelta
    from statistics import median
    from fastapi import HTTPException
    from ml.pipeline.preprocessing.gnss_rawx_time import canonical_rawx_utc

    if not from_time.tzinfo or not to_time.tzinfo or from_time >= to_time or to_time - from_time > timedelta(days=31):
        raise HTTPException(422, "Valid timezone-aware window (up to 31 days) required")
    if device_id not in ("BASE-01", "ROVER-B1-01", "ROVER-B1-02"):
        raise HTTPException(422, "Unsupported GNSS device")
    async with get_db_pool(request).acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.time, r.raw_payload_base64
            FROM gnss_raw_samples r JOIN devices d ON d.device_id=r.device_id
            WHERE d.site_id=$1 AND r.device_id=$2 AND r.time >= $3 AND r.time <= $4
            ORDER BY r.time LIMIT 10001
        """, site_id, device_id, from_time - timedelta(hours=8), to_time + timedelta(hours=8))
    if len(rows) > 10000:
        raise HTTPException(422, "RAWX scan limit exceeded: narrow time window")
    epochs, hist, systems = [], Counter(), Counter()
    invalid = excluded = sample_count = 0
    for row in rows:
        try:
            frame = base64.b64decode(row["raw_payload_base64"], validate=True)
            t = canonical_rawx_utc(frame, row["time"])
            if not from_time <= t <= to_time:
                continue
            if len(frame) < 24 or frame[:4] != bytes.fromhex("b5620215"):
                raise ValueError("invalid RAWX frame")
            length = int.from_bytes(frame[4:6], "little")
            num = frame[17]  # payload numMeas byte, frame offset = 6 + 11
            if length != 16 + 32 * num or len(frame) != length + 8:
                raise ValueError("invalid RAWX payload length")
            ck_a = ck_b = 0
            for octet in frame[2:-2]:
                ck_a = (ck_a + octet) & 255
                ck_b = (ck_b + ck_a) & 255
            if frame[-2:] != bytes((ck_a, ck_b)):
                raise ValueError("invalid RAWX checksum")
            unique, strengths = set(), []
            for i in range(num):
                off = 22 + i * 32
                gnss, sv, cn = frame[off + 20], frame[off + 21], frame[off + 26]
                if gnss > 7 or sv == 0:
                    excluded += 1
                    continue
                unique.add((gnss, sv)); systems[str(gnss)] += 1
                if 0 < cn <= 70:
                    strengths.append(cn)
                    hist[(cn // 5) * 5] += 1
                    sample_count += 1
                else:
                    excluded += 1
            epochs.append({"timestamp_utc": t.isoformat(), "unique_satellites": len(unique),
                           "num_meas": num, "median_cn0_dbhz": median(strengths) if strengths else None,
                           "cn0_samples": len(strengths)})
        except (ValueError, TypeError, binascii.Error, struct.error, IndexError):
            invalid += 1
    epochs.sort(key=lambda x: x["timestamp_utc"])
    return {"schema_version": "sensor.gnss.rawx.satellite_quality.qa.v1", "source": "actual",
            "site_id": site_id, "device_id": device_id, "requested_window": {"from": from_time.isoformat(), "to": to_time.isoformat()},
            "time_basis": "verified_ubx_rxm_rawx_utc", "validation_status": "experimental",
            "epochs": epochs, "cn0_sample_count": sample_count,
            "cn0_histogram": [{"start_dbhz": i, "count": hist[i]} for i in range(0, 75, 5)],
            "constellations": dict(sorted(systems.items())), "invalid_rawx": invalid,
            "excluded_measurements": excluded, "interpolation": "none"}

@router.get("/gnss/rawx/availability")
async def get_rawx_availability(
    request: Request, site_id: str,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    user: TokenPayload = Depends(require_role("viewer")),
) -> dict:
    """Bounded, read-only time-bucket telemetry; timestamp is verified GNSS UTC.

    Historical CSV-local-time rows and normalized new rows coexist in storage.
    No change to persisted epoch keys, no PPK inference, no interpolation.
    """
    import base64
    import binascii
    from collections import defaultdict
    from datetime import timedelta, timezone
    from statistics import median
    from fastapi import HTTPException
    from ml.pipeline.preprocessing.gnss_rawx_time import canonical_rawx_utc

    if any(t is not None and t.tzinfo is None for t in (from_time, to_time)):
        raise HTTPException(status_code=422, detail="timezone-aware from/to required")
    end = to_time or datetime.now(timezone.utc)
    start = from_time or end - timedelta(days=7)
    if start >= end or end - start > timedelta(days=31):
        raise HTTPException(status_code=422, detail="window must be positive and at most 31 days")

    seconds = (end - start).total_seconds()
    bucket_seconds = 300 if seconds <= 86400 else (3600 if seconds <= 7 * 86400 else 86400)
    # A bounded candidate scan rather than per-file API output. If the cap is
    # exceeded, return a clear error instead of silently reporting partial data.
    max_scanned = 300000
    chunk_size = 5000
    scanned = invalid = 0
    buckets = defaultdict(int)
    epoch_count = defaultdict(int)
    observed_times = defaultdict(list)
    earliest, latest = {}, {}
    cursor = None
    lower, upper = start - timedelta(hours=8), end + timedelta(hours=8)
    pool = get_db_pool(request)
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            while True:
                rows = await conn.fetch("""
                    SELECT r.device_id, r.file_name, r.time, r.raw_payload_base64
                    FROM gnss_raw_samples r
                    JOIN devices d ON d.device_id = r.device_id
                    WHERE d.site_id = $1 AND r.time >= $2 AND r.time <= $3
                      AND ($4::timestamptz IS NULL OR (r.time, r.device_id) > ($4, $5))
                    ORDER BY r.time, r.device_id
                    LIMIT $6
                """, site_id, lower, upper,
                    cursor[0] if cursor else None,
                    cursor[1] if cursor else None, chunk_size)
                if not rows:
                    break
                scanned += len(rows)
                if scanned > max_scanned:
                    raise HTTPException(status_code=422, detail="RAWX scan budget exceeded; narrow time window")
                for r in rows:
                    cursor = (r["time"], r["device_id"])
                    try:
                        raw = base64.b64decode(r["raw_payload_base64"], validate=True)
                        t = canonical_rawx_utc(raw, r["time"])
                    except (ValueError, TypeError, binascii.Error):
                        invalid += 1
                        continue
                    if not start <= t <= end:
                        continue
                    dev = r["device_id"]
                    bucket = int(t.timestamp() // bucket_seconds * bucket_seconds)
                    buckets[(dev, bucket)] += 1
                    epoch_count[dev] += 1
                    earliest[dev] = min(earliest.get(dev, t), t)
                    latest[dev] = max(latest.get(dev, t), t)
                    observed_times[dev].append(t)
                if len(rows) < chunk_size:
                    break
    from datetime import datetime as _dt
    points = []
    # Explicit zero-count buckets show actual gaps, but only inside each device's
    # observed span (never fabricate data outside known monitoring coverage).
    for dev in sorted(epoch_count):
        first_bucket = int(earliest[dev].timestamp() // bucket_seconds * bucket_seconds)
        last_bucket = int(latest[dev].timestamp() // bucket_seconds * bucket_seconds)
        for sec in range(first_bucket, last_bucket + 1, bucket_seconds):
            points.append({"device_id": dev,
                           "bucket_utc": _dt.fromtimestamp(sec, timezone.utc).isoformat(),
                           "epochs": buckets.get((dev, sec), 0)})
    devices = []
    for dev in sorted(epoch_count):
        ordered = sorted(set(observed_times[dev]))
        gaps = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
        devices.append({"device_id":dev, "epochs":epoch_count[dev],
                        "first_epoch":earliest[dev].isoformat(), "last_epoch":latest[dev].isoformat(),
                        "median_interval_s":median(gaps) if gaps else None,
                        "max_gap_s":max(gaps) if gaps else None,
                        "gaps_over_20s":sum(g > 20 for g in gaps)})
    return {"schema_version":"sensor.gnss.rawx.availability.v3", "source":"actual",
            "site_id":site_id,"interpolation":"none", "time_basis":"verified_ubx_rxm_rawx_utc",
            "position_validation":"not_applicable", "bucket_seconds":bucket_seconds,
            "requested_window":{"from":start.isoformat(),"to":end.isoformat()},
            "points":points,"devices":devices,"invalid_time_candidates":invalid,
            "scanned_candidates":scanned}


@router.get("/accel/events")
async def list_accel_events(
    request: Request,
    site_id: str | None = None,
    device_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: TokenPayload = Depends(require_role("viewer")),
) -> dict:
    pool = get_db_pool(request)
    rows = await SensorReadRepository(pool).list_accel_events(
        site_id=site_id, device_id=device_id, limit=limit,
    )
    # RAW existence is authoritative; event.sample_count is metadata, not proof.
    raw_by_file = {}
    if rows:
        filenames = sorted({r["source_file"] for r in rows if r["source_file"]})
        devices = sorted({r["device_id"] for r in rows if r["device_id"]})
        if filenames and devices:
            async with pool.acquire() as conn:
                raw_counts = await conn.fetch(
                    """SELECT device_id, file_name, COUNT(*)::bigint AS actual_raw_rows
                       FROM accel_raw_samples
                       WHERE device_id = ANY($1::text[])
                         AND file_name = ANY($2::text[])
                       GROUP BY device_id, file_name""",
                    devices, filenames,
                )
            raw_by_file = {(r["device_id"], r["file_name"]): r["actual_raw_rows"] for r in raw_counts}
    return {
        "schema_version": "sensor.accel.events.v1",
        "source": "actual",
        "validation_status": "unvalidated",
        "events": [{
            "event_id": r["event_id"], "site_id": r["site_id"],
            "device_id": r["device_id"],
            "blast_command_id": r["blast_command_id"],
            "source_file": r["source_file"],
            "actual_raw_samples": raw_by_file.get((r["device_id"], r["source_file"]), 0),
            "raw_available": raw_by_file.get((r["device_id"], r["source_file"]), 0) > 0,
            "communication_mode": r["communication_mode"],
            "event_start": _iso(r["event_start"]),
            "event_end": _iso(r["event_end"]),
            "sample_count": r["sample_count"], "duration_ms": r["duration_ms"],
            "observed_sample_rate_hz": r["observed_sample_rate_hz"],
            "median_gap_ms": r["median_gap_ms"], "max_gap_ms": r["max_gap_ms"],
            "quality_gate_status": r["quality_gate_status"],
            "quality_reasons": r["quality_reasons"],
            "adxl355_ppa_g": r["adxl355_ppa_g"],
            "adxl355_ppv_mm_s": r["adxl355_ppv_mm_s"],
            "mpu9250_ppa_g": r["mpu9250_ppa_g"],
            "mpu9250_ppv_mm_s": r["mpu9250_ppv_mm_s"],
            "validation_status": r["validation_status"],
            "upload_origin": r["upload_origin"],
            "source_received_at": _iso(r["source_received_at"]),
        } for r in rows],
    }


@router.get("/accel/waveform")
async def get_accel_waveform(
    request: Request,
    file_name: str,
    device_id: str | None = None,
    max_points: int = Query(default=DEFAULT_MAX_POINTS, ge=2, le=HARD_MAX_POINTS),
    user: TokenPayload = Depends(require_role("viewer")),
) -> dict:
    result = await SensorReadRepository(get_db_pool(request)).get_accel_waveform(
        file_name=file_name, device_id=device_id, max_points=max_points,
    )
    stride = result["stride"]
    return {
        "schema_version": "sensor.accel.waveform.v1",
        "source": "actual",
        "source_file": file_name,
        "device_id": device_id,
        "interpolation": "none",
        "validation_status": "unvalidated",
        "total_samples": result["total_samples"],
        "returned_samples": result["returned_samples"],
        "downsampling": {
            "method": "none" if stride == 1 else "deterministic_stride",
            "stride": stride,
            "note": "Display transport only; raw persisted samples remain authoritative.",
        },
        "rows": [{
            "timestamp_utc": _iso(r["time"]),
            "device_id": r["device_id"], "sample_index": r["sample_index"],
            "adxl355_x_mps2": r["adxl355_x_mps2"],
            "adxl355_y_mps2": r["adxl355_y_mps2"],
            "adxl355_z_mps2": r["adxl355_z_mps2"],
            "mpu9250_x_mps2": r["mpu9250_x_mps2"],
            "mpu9250_y_mps2": r["mpu9250_y_mps2"],
            "mpu9250_z_mps2": r["mpu9250_z_mps2"],
            "blast_command_id": r["blast_command_id"],
            "source_file": r["file_name"],
        } for r in result["rows"]],
    }
