from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from apps.api.dependencies import get_db_pool, require_role, require_role_and_mfa
from common.security import TokenPayload
from services.blast_service import reset_blast_atomic, trigger_blast_atomic
from services.monitoring_service.blast_event_repository import BlastEventRepository

router = APIRouter(prefix="/api/v1/blast", tags=["blast"])

class TriggerRequest(BaseModel):
    base_id: str
    # API contract: TimeOutTrigger is expressed in minutes, not seconds.
    timeout_minutes: int | None = Field(default=None, gt=0)

class ResetRequest(BaseModel):
    base_id: str

@router.post("/trigger")
async def trigger_blast(
    body: TriggerRequest,
    request: Request,
    user: TokenPayload = Depends(require_role_and_mfa("operator")),
) -> dict:
    pool = get_db_pool(request)
    # Config, pending config, command ledger, and audit are committed atomically.
    command_id = await trigger_blast_atomic(
        pool, body.base_id, body.timeout_minutes, user.sub
    )
    return {"ok": True, "command_id": command_id, "TriggerStart": 1, "delivery": "config"}

@router.post("/reset")
async def reset_blast_trigger(
    body: ResetRequest,
    request: Request,
    user: TokenPayload = Depends(require_role_and_mfa("operator")),
) -> dict:
    pool = get_db_pool(request)
    # Reset and audit share the same transaction. TimeOutTrigger is intentionally preserved.
    await reset_blast_atomic(pool, body.base_id, user.sub)
    return {"ok": True, "TriggerStart": 0}


@router.get("/events")
async def list_blast_events(
    request: Request,
    user: TokenPayload = Depends(require_role("viewer")),
    site_id: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    rows = await BlastEventRepository(get_db_pool(request)).list_events(
        site_id=site_id, device_id=device_id, limit=limit,
    )
    return {
        "schema_version": "blast.event.v1",
        "validation_status": "unvalidated",
        "operational_ready": False,
        "events": [
            {
                "event_id": row["event_id"],
                "site_id": row["site_id"],
                "device_id": row["device_id"],
                "blast_command_id": row["blast_command_id"],
                "source_file": row["source_file"],
                "communication_mode": row["communication_mode"],
                "event_start": row["event_start"].isoformat(),
                "event_end": row["event_end"].isoformat(),
                "sample_count": row["sample_count"],
                "duration_ms": row["duration_ms"],
                "observed_sample_rate_hz": row["observed_sample_rate_hz"],
                "median_gap_ms": row["median_gap_ms"],
                "max_gap_ms": row["max_gap_ms"],
                "quality_gate_status": row["quality_gate_status"],
                "quality_reasons": row["quality_reasons"],
                "adxl355_ppa_g": row["adxl355_ppa_g"],
                "adxl355_ppv_mm_s": row["adxl355_ppv_mm_s"],
                "mpu9250_ppa_g": row["mpu9250_ppa_g"],
                "mpu9250_ppv_mm_s": row["mpu9250_ppv_mm_s"],
                "validation_status": row["validation_status"],
                "processed_at": row["processed_at"].isoformat(),
            }
            for row in rows
        ],
    }
