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
    timeout_minutes: int = Field(gt=0, strict=True)

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


# ITB 4G v1.9 / LoRa v1.7 device acknowledgment.
from datetime import datetime
from typing import Literal
from fastapi import Header, HTTPException

from services.device_config_service.trigger_ack_service import (
    acknowledge_trigger_start,
)


class TriggerAckRequest(BaseModel):
    device_id: str
    trigger_start: Literal[0, 1]
    received: Literal[True]
    timestamp_utc: str


@router.post("/trigger-ack")
async def trigger_ack(
    body: TriggerAckRequest,
    request: Request,
    x_device_id: str = Header(..., alias="X-Device-Id"),
    x_device_role: str = Header(..., alias="X-Device-Role"),
    x_iccid: str = Header(..., alias="X-ICCID"),
    x_device_version: str = Header(..., alias="X-Device-Version"),
) -> dict:
    if body.device_id != x_device_id:
        raise HTTPException(
            status_code=400,
            detail="device_id does not match X-Device-Id",
        )

    # ITB permits an empty timestamp when the device clock is unset.
    if body.timestamp_utc:
        try:
            datetime.strptime(
                body.timestamp_utc, "%Y-%m-%d %H:%M:%S"
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="invalid timestamp_utc",
            ) from exc

    device_timestamp = (
        datetime.strptime(body.timestamp_utc, "%Y-%m-%d %H:%M:%S")
        if body.timestamp_utc else None
    )

    accepted = await acknowledge_trigger_start(
        get_db_pool(request),
        device_id=x_device_id,
        trigger_start=body.trigger_start,
        device_role=x_device_role,
        iccid=x_iccid,
        device_version=x_device_version,
        device_timestamp_utc=device_timestamp,
    )

    if not accepted:
        raise HTTPException(
            status_code=409,
            detail="no matching active TriggerStart command",
        )

    return {"ok": True}

@router.get('/trigger-status')
async def trigger_status(
    request: Request,
    base_id: str = Query(..., min_length=1, max_length=128),
    user: TokenPayload = Depends(require_role('viewer')),
) -> dict:
    """Operator read model; ACK refers to the *latest pending command*, not a stale value."""
    pool = get_db_pool(request)
    async with pool.acquire() as conn:
        config = await conn.fetchrow('''
            SELECT config_value, updated_at FROM public.device_config
            WHERE device_id=$1 AND config_key='TriggerStart'
        ''', base_id)
        pending = await conn.fetchrow('''
            SELECT id, config_value, created_at, acked_at
            FROM public.device_config_pending
            WHERE device_id=$1 AND config_key='TriggerStart'
            ORDER BY created_at DESC, id DESC LIMIT 1
        ''', base_id)
        ack = None
        if pending:
            ack = await conn.fetchrow('''
                SELECT trigger_start, device_timestamp_utc, server_received_at,
                       device_role, device_version
                FROM public.blast_trigger_acks
                WHERE device_id=$1 AND pending_config_id=$2
                ORDER BY server_received_at DESC, id DESC LIMIT 1
            ''', base_id, pending['id'])
        timeout = await conn.fetchrow('''
            SELECT started_at, expired_at FROM public.blast_trigger_timeout_events
            WHERE device_id=$1 ORDER BY expired_at DESC, id DESC LIMIT 1
        ''', base_id)
        recent_acks = await conn.fetch('''
            SELECT a.id, a.trigger_start, a.pending_config_id,
                   a.server_received_at, a.device_timestamp_utc
            FROM public.blast_trigger_acks a
            WHERE a.device_id=$1 ORDER BY a.server_received_at DESC, a.id DESC LIMIT 10
        ''', base_id)
        recent_timeouts = await conn.fetch('''
            SELECT id, expired_at, started_at FROM public.blast_trigger_timeout_events
            WHERE device_id=$1 ORDER BY expired_at DESC, id DESC LIMIT 10
        ''', base_id)

    def iso(value):
        return value.isoformat() if value is not None else None

    def boolean_integer(value):
        import json
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return None
        if value is True or value == 1:
            return 1
        if value is False or value == 0:
            return 0
        return None

    server_value = boolean_integer(config['config_value']) if config else None
    pending_value = boolean_integer(pending['config_value']) if pending else None
    current_pending = bool(
        config and pending and pending_value == server_value
        and pending['created_at'] >= config['updated_at']
    )
    # The transactional reconciler writes the audit event at the same time as RESET.
    timeout_is_current = bool(
        config and timeout and server_value == 0
        and config['updated_at'] >= timeout['expired_at']
        and abs((config['updated_at'] - timeout['expired_at']).total_seconds()) < 5
    )
    ack_matches = bool(current_pending and ack and ack['trigger_start'] == server_value)
    events = [
        dict(kind='DEVICE_ACK', trigger_start=row['trigger_start'],
             occurred_at=iso(row['server_received_at']),
             device_timestamp_utc=iso(row['device_timestamp_utc']),
             pending_config_id=row['pending_config_id'])
        for row in recent_acks
    ] + [
        dict(kind='AUTO_TIMEOUT_RESET', trigger_start=0,
             occurred_at=iso(row['expired_at']),
             started_at=iso(row['started_at']))
        for row in recent_timeouts
    ]
    events.sort(key=lambda e: e['occurred_at'] or '', reverse=True)
    return {
        'base_id': base_id,
        'server': {'trigger_start': server_value,
                   'updated_at': iso(config['updated_at']) if config else None,
                   'reset_reason': 'AUTO_TIMEOUT' if timeout_is_current else None},
        'delivery': {
            'pending_config_id': pending['id'] if current_pending else None,
            'trigger_start': pending_value if current_pending else None,
            'acked': bool(ack_matches),
            'pending': bool(current_pending and not ack_matches),
            'ack_server_at': iso(ack['server_received_at']) if ack_matches else None,
            'ack_device_utc': iso(ack['device_timestamp_utc']) if ack_matches else None,
            'device_role': ack['device_role'] if ack_matches else None,
            'device_version': ack['device_version'] if ack_matches else None,
        },
        'events': events[:20],
        'notes': 'Device ACK is a report of stored configuration, not physical blast confirmation.',
    }
