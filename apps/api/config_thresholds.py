"""Extends the EXISTING `consumers/api/config.py` THRESHOLDS dict (blueprint
§2.1/§10.2 — pattern preserved, not replaced). Ship this as an addition to
that file, not a separate config system, so `status_for()` keeps working
unchanged for every quantity, old and new.

New quantities added for this project (§2.1):
  - ppa / ppv: blast vibration output — diagnostic only (no threshold),
    same rationale as the existing disp_e/disp_n/disp_u rows: they are the
    inputs an engineer reads directly, not a value the 3-tier status should
    trigger on.
  - vibration_dominant_hz: diagnostic only, matches the existing
    loadgen `vibration()` convention ("no threshold, dashboard flags
    spikes as anomaly events instead").
  - h_acc_m / gnss_fix_type: GNSS fix quality — diagnostic only. These
    exist so a low-confidence displacement reading can be visually
    distinguished on the chart, NOT so a bad fix triggers a false alarm.
  - battery_voltage: device health, not slope health — deliberately has no
    siaga/bahaya entry; a dead battery is a device-health alert, and mixing
    it into the same 3-tier status as ground movement would let a flat
    battery mask (or fake) a real slope alarm.
"""

from __future__ import annotations

# Import and merge into the existing THRESHOLDS dict at the call site:
#   from apps.api.config_thresholds import NEW_THRESHOLDS
#   THRESHOLDS.update(NEW_THRESHOLDS)  # in consumers/api/config.py
NEW_THRESHOLDS: dict[str, dict] = {
    # Deliberately absent from this dict (by design, not omission):
    # 'ppa', 'ppv', 'vibration_dominant_hz', 'h_acc_m', 'gnss_fix_type',
    # 'battery_voltage' — diagnostic-only quantities, same status as
    # disp_e/disp_n/disp_u in the original THRESHOLDS docstring.
}

# Quantities that must NEVER drive `status_for()` — used by a unit test
# (tests/unit/test_thresholds.py) to assert the diagnostic-only list above
# doesn't silently grow a threshold entry by accident in a future edit.
DIAGNOSTIC_ONLY_QUANTITIES = frozenset(
    {"ppa", "ppv", "vibration_dominant_hz", "h_acc_m", "gnss_fix_type", "battery_voltage",
     "disp_e", "disp_n", "disp_u"}
)
