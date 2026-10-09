from ml.pipeline.preprocessing.ppk_time_integrity import (
    assess_clock_deltas,
    assess_receiver_epochs,
    assess_receiver_overlap,
)


def test_source_clock_integrity_is_diagnostic_not_pairing_gate():
    aligned = assess_clock_deltas([0.2, -0.1, 0.4])
    assert aligned["status"] == "ALIGNED"
    assert aligned["pairing_time_basis"] == "rxm_rawx_gps_seconds"
    assert aligned["acceptance_blocking"] is False

    offset = assess_clock_deltas([25159.005, 25160.005])
    assert offset["status"] == "SUSPECT_STABLE_OFFSET"
    assert offset["offset_spread_s"] == 1.0
    assert offset["acceptance_blocking"] is False

    anomaly = assess_clock_deltas([-1.986, 25198.014])
    assert anomaly["status"] == "ANOMALOUS_SOURCE_CLOCK"
    assert anomaly["acceptance_blocking"] is False


def test_receiver_epoch_integrity_is_acceptance_gate():
    good = assess_receiver_epochs([1000.0, 1015.0, 1030.0])
    assert good["status"] == "MONOTONIC"
    assert good["acceptance_blocking"] is False
    assert good["max_gap_s"] == 15.0

    duplicate = assess_receiver_epochs([1000.0, 1000.0, 1015.0])
    assert duplicate["status"] == "MONOTONIC"
    assert duplicate["duplicate_epoch_count"] == 1
    assert duplicate["acceptance_blocking"] is False

    bad = assess_receiver_epochs([1000.0, 1015.0, 1005.0])
    assert bad["status"] == "NON_MONOTONIC"
    assert bad["non_monotonic_count"] == 1
    assert bad["acceptance_blocking"] is True


def test_receiver_overlap_uses_internal_gnss_epoch_ranges():
    overlap = assess_receiver_overlap(
        {"first_gps_seconds": 1000.0, "last_gps_seconds": 1300.0},
        {"first_gps_seconds": 1100.0, "last_gps_seconds": 1400.0},
    )
    assert overlap["status"] == "OVERLAP"
    assert overlap["overlap_seconds"] == 200.0
    assert overlap["pairing_time_basis"] == "rxm_rawx_gps_seconds"

    no_overlap = assess_receiver_overlap(
        {"first_gps_seconds": 1000.0, "last_gps_seconds": 1050.0},
        {"first_gps_seconds": 1100.0, "last_gps_seconds": 1200.0},
    )
    assert no_overlap["status"] == "NO_OVERLAP"
    assert no_overlap["overlap_seconds"] == 0.0
