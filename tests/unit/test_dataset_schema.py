from datetime import datetime, timedelta, timezone

import pytest

from ml.domain.dataset_schema import (
    DATASET_SCHEMA_VERSION,
    FeatureDefinition,
    FeatureMetadata,
    MLSourceKind,
    MLValidationStatus,
    MISSING_METADATA,
    RegressionTarget,
    TemporalGraphSample,
)


UTC = timezone.utc


def _meta():
    return FeatureMetadata(
        source_kind=MLSourceKind.DERIVED,
        validation_status=MLValidationStatus.UNVERIFIED,
        quality_flag="accepted",
        source_file="example.csv",
    )


def _target(window_end, value=2.5, available=True):
    return RegressionTarget(
        device_id="ROVER-B1-01",
        quantity="future_displacement",
        unit="mm",
        horizon_s=3600.0,
        target_timestamp_utc=window_end + timedelta(hours=1),
        value=value,
        available=available,
        source_kind=MLSourceKind.DERIVED,
        validation_status=MLValidationStatus.UNVALIDATED,
        provenance_ref="ppk.solution.v1",
    )


def _sample():
    t0 = datetime(2026, 10, 11, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)
    meta = _meta()

    return TemporalGraphSample(
        schema_version=DATASET_SCHEMA_VERSION,
        site_id="ITB-STAGING-01",
        device_ids=("ROVER-B1-01", "ROVER-B1-02"),
        feature_definitions=(
            FeatureDefinition("total_mm", "mm"),
            FeatureDefinition("h_acc_m", "m"),
        ),
        timestamps_utc=(t0, t1),
        feature_values=(
            ((1.0, 0.02), (None, 0.03)),
            ((1.2, 0.02), (2.1, 0.03)),
        ),
        feature_mask=(
            ((True, True), (False, True)),
            ((True, True), (True, True)),
        ),
        feature_metadata=(
            ((meta, meta), (MISSING_METADATA, meta)),
            ((meta, meta), (meta, meta)),
        ),
        adjacency=((0.0, 1.0), (1.0, 0.0)),
        adjacency_method="fixed_geodetic",
        adjacency_provenance="surveyed installation topology",
        target=_target(t1),
    )


def test_feature_identity_contains_explicit_unit():
    sample = _sample()

    assert sample.feature_names == ("total_mm", "h_acc_m")
    assert sample.feature_units == ("mm", "m")


def test_missing_value_is_none_not_zero():
    sample = _sample()

    assert sample.feature_values[0][1][0] is None
    assert sample.feature_mask[0][1][0] is False
    assert sample.feature_metadata[0][1][0] == MISSING_METADATA


def test_dense_conversion_always_returns_mask():
    sample = _sample()

    dense, mask = sample.dense_features(fill_value=0.0)

    assert dense[0][1][0] == 0.0
    assert mask[0][1][0] is False

    assert dense[0][0][0] == 1.0
    assert mask[0][0][0] is True


def test_mask_false_with_numeric_value_is_rejected():
    sample = _sample()

    with pytest.raises(ValueError, match="feature_mask=False"):
        TemporalGraphSample(
            **{
                **sample.__dict__,
                "feature_values": (
                    ((1.0, 0.02), (999.0, 0.03)),
                    ((1.2, 0.02), (2.1, 0.03)),
                ),
            }
        )


def test_missing_value_requires_missing_metadata():
    sample = _sample()
    meta = _meta()

    with pytest.raises(
        ValueError,
        match="missing feature must use missing metadata",
    ):
        TemporalGraphSample(
            **{
                **sample.__dict__,
                "feature_metadata": (
                    ((meta, meta), (meta, meta)),
                    ((meta, meta), (meta, meta)),
                ),
            }
        )


def test_available_value_rejects_missing_metadata():
    sample = _sample()
    meta = _meta()

    with pytest.raises(
        ValueError,
        match="available feature cannot use missing metadata",
    ):
        TemporalGraphSample(
            **{
                **sample.__dict__,
                "feature_metadata": (
                    (
                        (MISSING_METADATA, meta),
                        (MISSING_METADATA, meta),
                    ),
                    ((meta, meta), (meta, meta)),
                ),
            }
        )


def test_naive_timestamp_is_rejected():
    sample = _sample()

    timestamps = (
        datetime(2026, 10, 11, 0, 0),
        sample.timestamps_utc[1],
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        TemporalGraphSample(
            **{
                **sample.__dict__,
                "timestamps_utc": timestamps,
            }
        )


def test_non_increasing_timestamps_are_rejected():
    sample = _sample()
    t = sample.timestamps_utc[0]

    with pytest.raises(ValueError, match="strictly increasing"):
        TemporalGraphSample(
            **{
                **sample.__dict__,
                "timestamps_utc": (t, t),
                "target": _target(t),
            }
        )


def test_nan_feature_is_rejected():
    sample = _sample()

    with pytest.raises(ValueError, match="feature value must be finite"):
        TemporalGraphSample(
            **{
                **sample.__dict__,
                "feature_values": (
                    ((float("nan"), 0.02), (None, 0.03)),
                    ((1.2, 0.02), (2.1, 0.03)),
                ),
            }
        )


def test_target_must_match_declared_horizon():
    sample = _sample()

    bad_target = RegressionTarget(
        device_id="ROVER-B1-01",
        quantity="future_displacement",
        unit="mm",
        horizon_s=7200.0,
        target_timestamp_utc=(
            sample.window_end_utc + timedelta(hours=1)
        ),
        value=2.5,
        available=True,
        source_kind=MLSourceKind.DERIVED,
        validation_status=MLValidationStatus.UNVALIDATED,
    )

    with pytest.raises(ValueError, match="target horizon"):
        TemporalGraphSample(
            **{
                **sample.__dict__,
                "target": bad_target,
            }
        )


def test_unavailable_target_cannot_carry_numeric_value():
    t = datetime(2026, 10, 11, tzinfo=UTC)

    with pytest.raises(ValueError, match="value=None"):
        RegressionTarget(
            device_id="R1",
            quantity="future_displacement",
            unit="mm",
            horizon_s=60.0,
            target_timestamp_utc=t,
            value=0.0,
            available=False,
            source_kind=MLSourceKind.DERIVED,
            validation_status=MLValidationStatus.UNVALIDATED,
        )


def test_duplicate_feature_names_are_rejected():
    sample = _sample()

    with pytest.raises(ValueError, match="feature names must be unique"):
        TemporalGraphSample(
            **{
                **sample.__dict__,
                "feature_definitions": (
                    FeatureDefinition("x", "mm"),
                    FeatureDefinition("x", "m"),
                ),
            }
        )
