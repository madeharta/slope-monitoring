from __future__ import annotations
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
}
_ORDER = {"normal": 0, "siaga": 1, "bahaya": 2}
ACTION: dict[str, str] = {
    "normal": "Within safe limits - no action.",
    "siaga": "Check field conditions, prepare evacuation route.",
    "bahaya": "Evacuate - immediate field response.",
}
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
