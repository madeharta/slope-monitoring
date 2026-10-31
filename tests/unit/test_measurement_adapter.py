from datetime import datetime, timezone
import pytest

from ml.domain.dataset_schema import FeatureDefinition, MLSourceKind
from ml.pipeline.adapters.measurement_adapter import adapt_measurement, adapt_measurements

TS = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
DEFS = {"rainfall_external": FeatureDefinition("rainfall_external", "mm"),
        "displacement": FeatureDefinition("displacement", "mm")}
PARAMS = dict(definitions=DEFS, site_id="ITB-STAGING-01", node_ids=("ROVER-B1-01",))


def record(**changes):
    row = dict(time=TS, device_id="WEATHER-API", site_id="ITB-STAGING-01",
               quantity="rainfall_external", value=0.0, unit="mm",
               source_kind="external", source_file="Open-Meteo",
               validation_status="not_applicable")
    row.update(changes)
    return row


def test_external_zero_preserved_as_observed_site_context():
    out = adapt_measurement(record(), **PARAMS)
    assert out.scope == "site"
    assert out.cell.value == 0.0 and out.cell.available
    assert out.cell.metadata.source_kind is MLSourceKind.EXTERNAL
    assert out.cell.metadata.source_file == "Open-Meteo"


def test_derived_is_physical_node_but_not_approved_ground_truth():
    out = adapt_measurement(record(device_id="ROVER-B1-01", quantity="displacement",
                                   source_kind="derived", validation_status="unverified",
                                   source_file="gnss.csv", value=4.1), **PARAMS)
    assert out.scope == "node" and out.cell.metadata.validation_status.value == "unverified"


@pytest.mark.parametrize("change", [
    {"source_kind": "missing"}, {"source_kind": "EXTERNAL"},
    {"validation_status": "unvalidated"}, {"validation_status": "missing"},
    {"unit": "m"}, {"site_id": "OTHER"},
    {"device_id": "ROVER-B1-01"}, {"source_file": None},
    {"value": float("nan")}, {"value": float("inf")}, {"value": None},
    {"time": datetime(2026, 10, 11)}, {"time": "2026-10-11"},
    {"quantity": "unknown"}, {"quality_flag": "BAD"},
])
def test_invalid_measurements_fail_closed(change):
    with pytest.raises(ValueError):
        adapt_measurement(record(**change), **PARAMS)


def test_duplicate_rejected_even_identical():
    with pytest.raises(ValueError, match="duplicate"):
        adapt_measurements([record(), record()], **PARAMS)


def test_two_observations_with_distinct_time_are_allowed():
    rows = (record(), record(time=datetime(2026,10,11,12,1,tzinfo=timezone.utc)))
    assert len(adapt_measurements(rows, **PARAMS)) == 2


def test_no_implicit_external_node():
    with pytest.raises(ValueError):
        adapt_measurement(record(), **(PARAMS | {"node_ids": ("WEATHER-API",)}))


def test_missing_required_provenance_fails():
    r = record()
    del r["source_kind"]
    with pytest.raises(ValueError):
        adapt_measurement(r, **PARAMS)


def test_received_at_retained_and_is_not_observation_time():
    from datetime import timedelta
    arrival = TS + timedelta(minutes=20)
    item = adapt_measurement(record(received_at=arrival), **PARAMS)
    assert item.timestamp_utc == TS
    assert item.received_at_utc == arrival
    assert item.availability_status == "known"
    assert item.feature_eligibility == "candidate_only"


def test_missing_received_at_not_claimed_available_for_asof():
    item = adapt_measurement(record(), **PARAMS)
    assert item.availability_status == "unknown"
    with pytest.raises(ValueError, match="received_at required"):
        adapt_measurement(record(), require_received_at=True, **PARAMS)


def test_unknown_quality_does_not_mean_pass():
    item = adapt_measurement(record(), **PARAMS)
    assert item.quality_status == "unknown"
    item2 = adapt_measurement(record(quality_flag="GOOD"), accepted_quality_flags=frozenset({"GOOD"}), **PARAMS)
    assert item2.quality_status == "explicitly_accepted"


def test_derived_is_never_implicitly_training_approved():
    item = adapt_measurement(record(device_id="ROVER-B1-01", quantity="displacement",
                                   source_kind="derived", validation_status="unverified",
                                   source_file=None, value=4.1), **PARAMS)
    assert item.provenance_status == "partial"
    assert item.feature_eligibility == "candidate_only"


def test_audit_collects_rejections_without_mutating_source():
    from ml.pipeline.adapters.measurement_adapter import audit_measurements
    good = record()
    bad = record(unit="m")
    rows = [good, bad, good]
    result = audit_measurements(rows, **PARAMS)
    assert result.total == 3 and len(result.accepted) == 1
    assert result.rejected_count == 2
    assert result.rejected[0][0] == 1 and result.rejected[1][0] == 2
    assert bad["unit"] == "m"


def test_malformed_received_at_rejected():
    with pytest.raises(ValueError, match="received_at"):
        adapt_measurement(record(received_at="2026-10-11"), **PARAMS)


def test_partial_external_provenance_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="external measurement requires source_file"):
        adapt_measurement(record(source_file=None), **PARAMS)
    item = adapt_measurement(
        record(source_file=None), allow_partial_external_provenance=True, **PARAMS
    )
    assert item.scope == "site"
    assert item.source_file is None and item.provenance_status == "partial"
    assert item.feature_eligibility == "candidate_only"


def test_timestamp_utc_normalizes_mixed_timezone_offsets():
    from datetime import timedelta
    plus_seven = timezone(timedelta(hours=7))
    local_time = datetime(2026, 10, 11, 19, tzinfo=plus_seven)
    item = adapt_measurement(record(time=local_time, received_at=local_time), **PARAMS)
    assert item.timestamp_utc == TS
    assert item.timestamp_utc.tzinfo is timezone.utc
    assert item.received_at_utc == TS
    assert item.received_at_utc.tzinfo is timezone.utc


def test_equivalent_instant_duplicate_rejected_with_mixed_offsets():
    from datetime import timedelta
    plus_seven = timezone(timedelta(hours=7))
    with pytest.raises(ValueError, match="duplicate"):
        adapt_measurements([record(), record(time=TS.astimezone(plus_seven))], **PARAMS)


def test_partial_provenance_audit_keeps_rejection_reasons():
    from ml.pipeline.adapters.measurement_adapter import audit_measurements
    rows = [record(source_file=None), record(unit="m"), record(time=TS.replace(minute=1))]
    result = audit_measurements(
        rows, allow_partial_external_provenance=True, **PARAMS
    )
    assert result.total == 3 and len(result.accepted) == 2
    assert result.accepted[0].provenance_status == "partial"
    assert result.rejected == ((1, "measurement unit mismatch"),)


def test_arrival_after_observation_remains_distinct_no_asof_approval():
    from datetime import timedelta
    item = adapt_measurement(
        record(received_at=TS + timedelta(days=3)),
        require_received_at=True, **PARAMS
    )
    assert item.received_at_utc > item.timestamp_utc
    assert item.feature_eligibility == "candidate_only"


def test_millisecond_negative_receipt_lag_preserved_not_silently_corrected():
    from datetime import timedelta
    before = TS - timedelta(milliseconds=1)
    item = adapt_measurement(record(received_at=before), require_received_at=True, **PARAMS)
    assert item.received_at_utc == before
    assert item.timestamp_utc == TS
    assert item.feature_eligibility == "candidate_only"
