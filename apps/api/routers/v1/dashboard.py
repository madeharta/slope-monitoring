"""GET /api/overview, GET /api/sites/{id}, GET /api/stream — item #6, the
dashboard-read API. Prefix is deliberately `/api`, NOT `/api/v1` like every
other router in this backend — apps/frontend/src/api.js already calls
these exact unversioned paths (inherited from the OLD backend's
convention), and changing them would mean also editing working frontend
code for no functional benefit. This is the one intentional inconsistency
in this codebase's URL versioning, and it's intentional, not an oversight.

Dashboard reads and SSE require a signed viewer-or-higher access token.
Frontend route gating is not an API security boundary.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from apps.api.dependencies import get_db_pool, require_role
from services.dashboard_service.overview_repository import OverviewRepository
from services.dashboard_service.site_series_repository import SiteSeriesRepository

router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(require_role("viewer"))])

_STREAM_POLL_INTERVAL_S = 2.0  # matches Overview.jsx/SlopeDetail.jsx's own 8s refetch cadence closely enough for a POC-scale live tail, without a message broker


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
    """Polling-based SSE — no message broker in this codebase (no
    LISTEN/NOTIFY wiring, no Redis). Same in-process pattern already used
    for weather's background loop (apps/api/routers/v1/weather.py).
    Acceptable at this POC's scale; a real production deployment with
    many concurrent dashboard viewers would want LISTEN/NOTIFY or a proper
    pub/sub instead of N independent polling loops (one per open SSE
    connection) — noted, not built, since nothing in this codebase needs
    it yet.
    """
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
                yield ": keepalive\n\n"  # SSE comment line — api.js's onmessage already ignores unparseable lines
            await asyncio.sleep(_STREAM_POLL_INTERVAL_S)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
