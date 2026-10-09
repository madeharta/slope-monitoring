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
    user: TokenPayload = Depends(require_role("viewer")),
) -> dict:
    if from_time and to_time and from_time >= to_time:
        from common.errors import AppError, ErrorCode
        raise AppError(ErrorCode.VALIDATION_ERROR, "from must be earlier than to")

    rows = await SensorReadRepository(get_db_pool(request)).list_gnss(
        site_id=site_id, device_id=device_id, from_time=from_time,
        to_time=to_time, limit=limit,
    )
    return {
        "schema_version": "sensor.gnss.v1",
        "source": "actual",
        "interpolation": "none",
        "validation_status": "unvalidated",
        "site_id": site_id,
        "device_id": device_id,
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


@router.get("/accel/events")
async def list_accel_events(
    request: Request,
    site_id: str | None = None,
    device_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: TokenPayload = Depends(require_role("viewer")),
) -> dict:
    rows = await SensorReadRepository(get_db_pool(request)).list_accel_events(
        site_id=site_id, device_id=device_id, limit=limit,
    )
    return {
        "schema_version": "sensor.accel.events.v1",
        "source": "actual",
        "validation_status": "unvalidated",
        "events": [{
            "event_id": r["event_id"], "site_id": r["site_id"],
            "device_id": r["device_id"],
            "blast_command_id": r["blast_command_id"],
            "source_file": r["source_file"],
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
