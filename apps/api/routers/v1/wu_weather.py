"""B15.12: authenticated Weather Underground observation history."""
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from common.security import TokenPayload
from apps.api.dependencies import require_role

router = APIRouter(prefix="/api/v1/weather/wu", tags=["weather-underground"])

@router.get("/observations")
async def observations(
    request: Request,
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0, le=500000),
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    user: TokenPayload = Depends(require_role("viewer")),
):
    station = os.environ.get("WU_STATION_ID")
    if not station:
        raise HTTPException(503, detail="Weather station not configured")
    if any(t is not None and t.tzinfo is None for t in (from_time, to_time)):
        raise HTTPException(422, detail="Date range must specify a timezone")
    if from_time and to_time and from_time >= to_time:
        raise HTTPException(422, detail="from must be earlier than to")
    if from_time and to_time and (to_time - from_time).days > 366:
        raise HTTPException(422, detail="Maximum date range is 366 days")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT station_id, observed_at, fetched_at, lat, lon, qc_status, payload
            FROM public.wu_weather_observations
            WHERE station_id=$1
              AND ($2::timestamptz IS NULL OR observed_at >= $2)
              AND ($3::timestamptz IS NULL OR observed_at < $3)
            ORDER BY observed_at DESC, id DESC
            LIMIT $4 OFFSET $5
        """, station, from_time, to_time, limit, offset)
    return {"ok": True, "station_id": station, "limit": limit, "offset": offset,
            "has_more": len(rows) == limit,
            "observations": [
                {"station_id": r["station_id"], "observed_at": r["observed_at"].isoformat(),
                 "fetched_at": r["fetched_at"].isoformat(), "lat": r["lat"], "lon": r["lon"],
                 "qc_status": r["qc_status"], "metrics": r["payload"]} for r in rows]}
