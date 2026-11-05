"""ITB battery telemetry writer; existing measurements hypertable, no schema changes."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from services.monitoring_service.measurements_writer import MeasurementsWriter


def voltage_from_header(raw: str | None) -> float | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


async def persist_four_g_battery(pool, *, device_id: str, voltage_header: str | None,
                                 uploaded_at: datetime, file_name: str) -> None:
    """One 4G header measurement belongs to HTTP uploader, at server receipt time."""
    voltage = voltage_from_header(voltage_header)
    if voltage is None:
        return
    if uploaded_at.tzinfo is None:
        raise ValueError('uploaded_at must be timezone-aware')
    async with pool.acquire() as conn:
        site_id = await conn.fetchval('SELECT site_id FROM public.devices WHERE device_id=$1', device_id)
    if site_id is None:
        raise ValueError('unknown 4G device')
    await MeasurementsWriter(pool).write_battery_points(
        [(device_id, site_id, uploaded_at.astimezone(timezone.utc), voltage)],
        source_file=file_name,
    )
