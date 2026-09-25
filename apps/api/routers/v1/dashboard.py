from __future__ import annotations
import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from apps.api.dependencies import get_db_pool
from services.dashboard_service.overview_repository import OverviewRepository
from services.dashboard_service.site_series_repository import SiteSeriesRepository
router = APIRouter(prefix="/api", tags=["dashboard"])
_STREAM_POLL_INTERVAL_S = 2.0
@router.get("/overview")
async def get_overview(request: Request) -> dict:
    return await OverviewRepository(get_db_pool(request)).get_overview()
@router.get("/sites/{site_id}")
async def get_site(
    site_id: str, request: Request, hours: int = Query(default=24, ge=1, le=720),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
) -> dict:
    return await SiteSeriesRepository(get_db_pool(request)).get_series(site_id, hours, from_time, to_time)
@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    pool = get_db_pool(request)
    async def event_generator():
        last_seen_received_at = None
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT now() AS t")
            last_seen_received_at = row["t"]
        while True:
            if await request.is_disconnected():
                break
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT site_id, device_id, quantity, value, unit, time, received_at
                    FROM measurements
                    WHERE received_at > $1
                      AND (quantity NOT IN ('displacement', 'disp_e', 'disp_n', 'disp_u')
                           OR EXISTS (SELECT 1 FROM rover_displacement_baselines b
                                      WHERE b.device_id = measurements.device_id
                                        AND measurements.time >= b.approved_at))
                    ORDER BY received_at ASC
                    LIMIT 500
                    """,
                    last_seen_received_at,
                )
            for r in rows:
                last_seen_received_at = r["received_at"]
                payload = {
                    "site_id": r["site_id"], "device_id": r["device_id"], "quantity": r["quantity"],
                    "value": r["value"], "unit": r["unit"], "t": r["time"].isoformat(),
                }
                yield f"data: {json.dumps(payload)}\n\n"
            if not rows:
                yield ": keepalive\n\n"
            await asyncio.sleep(_STREAM_POLL_INTERVAL_S)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
