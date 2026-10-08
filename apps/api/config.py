from __future__ import annotations

import os

# Unchanged from the existing consumers/api/config.py (blueprint §2.1/§10.2:
# the narrow/long `measurements` pattern and this threshold table are
# PRESERVED, not replaced). New rows for this project are appended below
# the original block, not interleaved, so a diff against the original file
# stays a clean append.
THRESHOLDS: dict[str, dict] = {
    "soil_moisture": {"dir": "high", "siaga": 40.0, "bahaya": 48.0},
    "moisture":      {"dir": "high", "siaga": 40.0, "bahaya": 48.0},
    "suction":       {"dir": "low",  "siaga": 15.0, "bahaya": 8.0},
    "pore_pressure": {"dir": "high", "siaga": 20.0, "bahaya": 30.0},
    "tilt":          {"dir": "high", "siaga": 1.0,  "bahaya": 1.5},
    "tilt_x":        {"dir": "high", "siaga": 1.5,  "bahaya": 2.25},
    "tilt_y":        {"dir": "high", "siaga": 1.5,  "bahaya": 2.25},
    "rainfall":      {"dir": "high", "siaga": 20.0, "bahaya": 40.0},
    "displacement":  {"dir": "high", "siaga": 6.0,  "bahaya": 10.0},
    # --- new for this project (§2.1) — deliberately no entries for
    # ppa, ppv, vibration_dominant_hz, h_acc_m, gnss_fix_type,
    # battery_voltage: diagnostic-only, see config_thresholds.py docstring.
}

_ORDER = {"normal": 0, "siaga": 1, "bahaya": 2}

# Technical severity is deliberately separated from operational action.
# Until field/geodetic acceptance is explicitly approved, the application
# remains fail-closed: Siaga/Bahaya may be shown for QA/research but MUST NOT
# authorize evacuation or other operational instructions.
TECHNICAL_ACTION: dict[str, str] = {
    "normal": (
        "Within configured technical thresholds; "
        "this is not a field-safety certification."
    ),
    "siaga": (
        "Technical warning threshold reached. Verify field conditions; "
        "operational response is suppressed pending validation."
    ),
    "bahaya": (
        "Technical danger threshold exceeded. Verify field conditions immediately; "
        "operational response is suppressed pending validation."
    ),
}

OPERATIONAL_ACTION: dict[str, str] = {
    "normal": "Within safe limits - no action.",
    "siaga": "Check field conditions, prepare evacuation route.",
    "bahaya": "Evacuate - immediate field response.",
}

# Legacy consumers importing ACTION remain fail-closed.
ACTION = TECHNICAL_ACTION

_OPERATIONAL_TRUE = {"1", "true", "yes", "on"}


def operational_alarms_enabled() -> bool:
    """Explicit production acceptance switch; unset/unknown = False."""
    value = os.getenv("OPERATIONAL_ALARMS_ENABLED", "")
    return value.strip().lower() in _OPERATIONAL_TRUE


def operational_alarm_for(status: str, enabled: bool | None = None) -> bool:
    if enabled is None:
        enabled = operational_alarms_enabled()
    return bool(enabled and status in {"siaga", "bahaya"})


def action_for(status: str, enabled: bool | None = None) -> str:
    if enabled is None:
        enabled = operational_alarms_enabled()

    actions = OPERATIONAL_ACTION if enabled else TECHNICAL_ACTION
    return actions.get(
        status,
        "Data belum cukup untuk menetapkan status lereng.",
    )


def status_for(quantity: str, value: float | None) -> str:
    t = THRESHOLDS.get(quantity)
    if t is None or value is None:
        return "normal"
    if t["dir"] == "high":
        if value >= t["bahaya"]:
            return "bahaya"
        if value >= t["siaga"]:
            return "siaga"
    else:
        if value <= t["bahaya"]:
            return "bahaya"
        if value <= t["siaga"]:
            return "siaga"
    return "normal"


def worst(statuses) -> str:
    best = "normal"
    for s in statuses:
        if _ORDER.get(s, 0) > _ORDER[best]:
            best = s
    return best
