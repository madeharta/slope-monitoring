"""Dashboard API. Registry-driven endpoints + one SSE stream, serving the
built React frontend as static files (single service).

Run (dev, with the Variant-A stack up):
    python consumers/api/main.py
Then the Vite dev server proxies /api to this. In production, `npm run build`
puts files in frontend/dist/ which this serves at /.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from consumers.api import config, db, stream  # noqa: E402


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    stream.start()
    yield
    await stream.stop()
    await db.close()


app = FastAPI(title="MAGRIS Dashboard API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def _reading_key(r: dict) -> tuple[str, str]:
    return (r["quantity"], r.get("unit") or "")


@app.get("/api/overview")
async def overview():
    """Level 1: one entry per slope (status + action + key reading), device
    health counts, and the alarm summary. Everything derived from the data."""
    site_rows = {s["site_id"]: s for s in await db.sites()}
    latest = await db.latest_readings()
    devs = await db.devices()

    per_site: dict[str, list[dict]] = defaultdict(list)
    for r in latest:
        per_site[r["site_id"]].append(r)

    slopes = []
    status_counts = {"normal": 0, "siaga": 0, "bahaya": 0}
    for site_id, meta in site_rows.items():
        readings = per_site.get(site_id, [])
        statuses = [config.status_for(r["quantity"], r["value"]) for r in readings]
        st = config.worst(statuses)
        status_counts[st] += 1
        # key reading = the reading driving the worst status, else the freshest
        key = None
        for r in readings:
            if config.status_for(r["quantity"], r["value"]) == st and st != "normal":
                key = r
                break
        if key is None and readings:
            key = max(readings, key=lambda x: x["time"])
        slopes.append({
            "site_id": site_id,
            "name": meta["name"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "status": st,
            "action": config.ACTION[st],
            "reading": None if key is None else {
                "quantity": key["quantity"], "value": key["value"],
                "unit": key["unit"], "depth_cm": key["depth_cm"],
            },
        })

    order = {"bahaya": 0, "siaga": 1, "normal": 2}
    slopes.sort(key=lambda s: order[s["status"]])

    online = sum(1 for d in devs if d["online"])
    return {
        "slopes": slopes,
        "status_counts": status_counts,
        "health": {
            "online": online,
            "offline": len(devs) - online,
            "total": len(devs),
        },
    }


@app.get("/api/quantities")
async def get_quantities():
    return await db.quantities()


@app.get("/api/sites/{site_id}")
async def site_detail(site_id: str, hours: int = 24):
    """Level 2: combined series, per-sensor cross-section, quality, status."""
    latest = await db.site_latest(site_id)
    statuses = [config.status_for(r["quantity"], r["value"]) for r in latest]
    st = config.worst(statuses)

    bucket = 1 if hours <= 1 else 5 if hours <= 6 else 15
    rows = await db.series(site_id, hours=hours, bucket_minutes=bucket)
    series: dict[str, dict] = {}
    for r in rows:
        q = r["quantity"]
        series.setdefault(q, {"quantity": q, "unit": r["unit"], "points": []})
        series[q]["points"].append([r["t"].isoformat(), None if r["value"] is None else round(r["value"], 3)])

    # cross-section: one node per (device, quantity) with a depth
    sensors = [
        {
            "device_id": r["device_id"], "quantity": r["quantity"],
            "depth_cm": r["depth_cm"], "value": r["value"], "unit": r["unit"],
            "status": config.status_for(r["quantity"], r["value"]),
        }
        for r in latest if r["depth_cm"] is not None
    ]
    sensors.sort(key=lambda s: s["depth_cm"])

    return {
        "site_id": site_id,
        "status": st,
        "action": config.ACTION[st],
        "thresholds": config.THRESHOLDS,
        "series": list(series.values()),
        "sensors": sensors,
        "quality": await db.data_quality(site_id),
    }


@app.get("/api/stream")
async def sse(request: Request):
    q = stream.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            stream.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


# Serve the built frontend (if present) — single-service deployment, with a
# SPA fallback so client-side routes (e.g. /sites/x) resolve on refresh.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    from fastapi.responses import FileResponse  # noqa: E402

    if (_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        f = _dist / full_path
        if full_path and f.is_file():
            return FileResponse(str(f))
        return FileResponse(str(_dist / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
