"""Canonical current technical-status semantics shared by dashboard endpoints.

Historical measurements remain queryable, but only fresh threshold-bearing
measurements may drive the *current* technical condition. Measurement time is
authoritative; delayed upload/receive time must not refresh an old observation.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from apps.api.config import THRESHOLDS, status_for, worst

_EVENT_TECHNICAL_MAX_AGE_SECONDS = int(os.getenv("TECHNICAL_EVENT_MAX_AGE_SECONDS", "900"))
_DISPLACEMENT_MAX_AGE_SECONDS = int(os.getenv("TECHNICAL_DISPLACEMENT_MAX_AGE_SECONDS", "1800"))
_RAINFALL_MAX_AGE_SECONDS = int(os.getenv("TECHNICAL_RAINFALL_MAX_AGE_SECONDS", "3600"))
_SENSOR_MAX_AGE_SECONDS = int(os.getenv("TECHNICAL_SENSOR_MAX_AGE_SECONDS", "3600"))

_EVENT_DERIVED_QUANTITIES = {"tilt_x", "tilt_y"}
_DISPLACEMENT_QUANTITIES = {"displacement", "disp_e", "disp_n", "disp_u"}
_RAINFALL_QUANTITIES = {"rainfall"}


def _get(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def technical_max_age_seconds(quantity: str) -> int:
    if quantity in _EVENT_DERIVED_QUANTITIES:
        return _EVENT_TECHNICAL_MAX_AGE_SECONDS
    if quantity in _DISPLACEMENT_QUANTITIES:
        return _DISPLACEMENT_MAX_AGE_SECONDS
    if quantity in _RAINFALL_QUANTITIES:
        return _RAINFALL_MAX_AGE_SECONDS
    return _SENSOR_MAX_AGE_SECONDS


def measurement_is_current(quantity: str, measurement_time, *, now: datetime | None = None) -> bool:
    if measurement_time is None:
        return False
    now = now or datetime.now(timezone.utc)
    if measurement_time.tzinfo is None:
        measurement_time = measurement_time.replace(tzinfo=timezone.utc)
    age_s = max(0.0, (now - measurement_time).total_seconds())
    return age_s <= technical_max_age_seconds(quantity)


def _reading_payload(row, *, include_depth: bool = False) -> dict:
    payload = {
        "value": _get(row, "value"),
        "unit": _get(row, "unit"),
        "quantity": _get(row, "quantity"),
        "time": _get(row, "time").isoformat() if _get(row, "time") else None,
    }
    if include_depth:
        payload["depth_cm"] = None
    return payload


def evaluate_current_technical_status(rows, *, now: datetime | None = None) -> dict:
    """Evaluate canonical current technical severity from measurement rows.

    Non-threshold quantities (for example external weather series) are ignored
    for current site severity. They remain available to their chart/history
    callers and therefore cannot manufacture a ``normal`` current condition.
    """
    now = now or datetime.now(timezone.utc)
    eligible = [r for r in rows if _get(r, "quantity") in THRESHOLDS]
    current = [
        r for r in eligible
        if measurement_is_current(_get(r, "quantity"), _get(r, "time"), now=now)
    ]

    statuses = [status_for(_get(r, "quantity"), _get(r, "value")) for r in current]
    site_status = worst(statuses) if statuses else "unknown"

    representative = None
    for row in current:
        if status_for(_get(row, "quantity"), _get(row, "value")) == site_status:
            representative = row
            break

    stale = [r for r in eligible if r not in current]
    newest_stale = max(stale, key=lambda r: _get(r, "time"), default=None)

    return {
        "technical_status": site_status,
        "technical_data_status": "fresh" if current else "stale" if eligible else "no_data",
        "representative": representative,
        "reading": _reading_payload(representative, include_depth=True) if representative else None,
        "latest_stale_reading": (
            _reading_payload(newest_stale) if newest_stale is not None and not current else None
        ),
    }
