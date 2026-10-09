from __future__ import annotations

from statistics import median

CLOCK_ALIGNED_MAX_ABS_OFFSET_S = 2.0
CLOCK_STABLE_MAX_SPREAD_S = 2.0


def assess_clock_deltas(deltas_s: list[float]) -> dict:
    """Classify source CSV clock behavior without making it a PPK pairing gate.

    CSV timestamps are retained as provenance. Pairing and engine acceptance use
    RXM-RAWX receiver epochs; source-clock anomalies must be surfaced, never
    silently corrected and never substituted for receiver time.
    """
    if not deltas_s:
        return {
            "status": "NO_RECEIVER_UTC",
            "sample_count": 0,
            "offset_median_s": None,
            "offset_min_s": None,
            "offset_max_s": None,
            "offset_spread_s": None,
            "pairing_time_basis": "rxm_rawx_gps_seconds",
            "acceptance_blocking": False,
        }

    minimum = min(deltas_s)
    maximum = max(deltas_s)
    center = median(deltas_s)
    spread = maximum - minimum
    if spread > CLOCK_STABLE_MAX_SPREAD_S:
        status = "ANOMALOUS_SOURCE_CLOCK"
    elif abs(center) <= CLOCK_ALIGNED_MAX_ABS_OFFSET_S:
        status = "ALIGNED"
    else:
        status = "SUSPECT_STABLE_OFFSET"

    return {
        "status": status,
        "sample_count": len(deltas_s),
        "offset_median_s": center,
        "offset_min_s": minimum,
        "offset_max_s": maximum,
        "offset_spread_s": spread,
        "pairing_time_basis": "rxm_rawx_gps_seconds",
        "acceptance_blocking": False,
    }


def assess_receiver_epochs(gps_seconds_values: list[float]) -> dict:
    if not gps_seconds_values:
        return {
            "status": "NO_USABLE_EPOCHS",
            "sample_count": 0,
            "duplicate_epoch_count": 0,
            "non_monotonic_count": 0,
            "max_gap_s": None,
            "acceptance_blocking": True,
        }

    duplicates = 0
    non_monotonic = 0
    positive_gaps: list[float] = []
    for previous, current in zip(gps_seconds_values, gps_seconds_values[1:]):
        delta = current - previous
        if delta == 0:
            duplicates += 1
        elif delta < 0:
            non_monotonic += 1
        else:
            positive_gaps.append(delta)

    status = "MONOTONIC" if non_monotonic == 0 else "NON_MONOTONIC"
    return {
        "status": status,
        "sample_count": len(gps_seconds_values),
        "duplicate_epoch_count": duplicates,
        "non_monotonic_count": non_monotonic,
        "max_gap_s": max(positive_gaps) if positive_gaps else None,
        "acceptance_blocking": non_monotonic > 0,
    }


def assess_receiver_overlap(base_info: dict, rover_info: dict) -> dict:
    base_start = float(base_info["first_gps_seconds"])
    base_end = float(base_info["last_gps_seconds"])
    rover_start = float(rover_info["first_gps_seconds"])
    rover_end = float(rover_info["last_gps_seconds"])
    start = max(base_start, rover_start)
    end = min(base_end, rover_end)
    overlaps = end >= start
    overlap = max(0.0, end - start)
    return {
        "status": "OVERLAP" if overlaps else "NO_OVERLAP",
        "pairing_time_basis": "rxm_rawx_gps_seconds",
        "overlap_start_gps_seconds": start if overlaps else None,
        "overlap_end_gps_seconds": end if overlaps else None,
        "overlap_seconds": overlap,
        "base_receiver_span_seconds": max(0.0, base_end - base_start),
        "rover_receiver_span_seconds": max(0.0, rover_end - rover_start),
    }
