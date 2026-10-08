from __future__ import annotations
NEW_THRESHOLDS: dict[str, dict] = {
}
DIAGNOSTIC_ONLY_QUANTITIES = frozenset(
    {"ppa", "ppv", "vibration_dominant_hz", "h_acc_m", "gnss_fix_type", "battery_voltage",
     "disp_e", "disp_n", "disp_u"}
)
