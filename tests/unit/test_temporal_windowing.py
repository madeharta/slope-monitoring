from datetime import datetime, timedelta, timezone

import pytest

from ml.domain.dataset_schema import (
    FeatureDefinition,
    FeatureMetadata,
    MLSourceKind,
    MLValidationStatus,
    MISSING_METADATA,
    RegressionTarget,
)
from ml.pipeline.windowing.temporal_windowing import (
    AlignedFeatureFrame,
    FeatureCell,
    build_temporal_graph_sample,
    select_trailing_frames,
)


UTC = timezone.utc


def _meta(source_kind=MLSourceKind.DERIVED):
    return FeatureMetadata(
        source_kind=source_kind,
        validation_status=(
            MLValidationStatus.NOT_APPLICABLE
            if source_kind is MLSourceKind.EXTERNAL
            else MLValidationStatus.UNVERIFIED
        ),
        quality_flag="accepted",
    )


def _target(window_end):
    return RegressionTarget(
        device_id="ROVER-B1-01",
        quantity="future_displacement",
        unit="mm",
        horizon_s=300.0,
        target_timestamp_utc=window_end + timedelta(minutes=5),
        value=None,
        available=False,
        source_kind=MLSourceKind.DERIVED,
        validation_status=MLValidationStatus.UNVALIDATED,
        provenance_ref="awaiting production geodetic acceptance",
    )


def test_missing_feature_remains_missing_not_zero():
    t0 = datetime(2026, 10, 11, 0, 0, tzinfo=UTC)

    frame = AlignedFeatureFrame(
        timestamp_utc=t0,
        values={
            "ROVER-B1-01": {
                "total_mm": FeatureCell(1.5, _meta()),
            }
        },
    )

    sample = build_temporal_graph_sample(
        site_id="ITB-STAGING-01",
        device_ids=("ROVER-B1-01",),
        feature_definitions=(
            FeatureDefinition("total_mm", "mm"),
            FeatureDefinition("ppa_g", "g"),
        ),
        frames=(frame,),
        adjacency=((0.0,),),
        adjacency_method="fixed_geodetic",
        adjacency_provenance="installation topology",
        target=_target(t0),
    )

    assert sample.feature_values[0][0][0] == 1.5
    assert sample.feature_mask[0][0][0] is True

    assert sample.feature_values[0][0][1] is None
    assert sample.feature_mask[0][0][1] is False
    assert sample.feature_metadata[0][0][1] == MISSING_METADATA


def test_physical_zero_is_distinct_from_missing():
    t0 = datetime(2026, 10, 11, 0, 0, tzinfo=UTC)

    frame = AlignedFeatureFrame(
        timestamp_utc=t0,
        values={
            "ROVER-B1-01": {
                "ppa_g": FeatureCell(0.0, _meta()),
            }
        },
    )

    sample = build_temporal_graph_sample(
        site_id="ITB-STAGING-01",
        device_ids=("ROVER-B1-01",),
        feature_definitions=(
            FeatureDefinition("ppa_g", "g"),
            FeatureDefinition("tilt_x_deg", "deg"),
        ),
        frames=(frame,),
        adjacency=((0.0,),),
        adjacency_method="fixed_geodetic",
        adjacency_provenance="installation topology",
        target=_target(t0),
    )

    assert sample.feature_values[0][0][0] == 0.0
    assert sample.feature_mask[0][0][0] is True

    assert sample.feature_values[0][0][1] is None
    assert sample.feature_mask[0][0][1] is False


def test_device_and_feature_order_is_contractual():
    t0 = datetime(2026, 10, 11, 0, 0, tzinfo=UTC)

    frame = AlignedFeatureFrame(
        timestamp_utc=t0,
        values={
            "B": {
                "f2": FeatureCell(22.0, _meta()),
                "f1": FeatureCell(21.0, _meta()),
            },
            "A": {
                "f2": FeatureCell(12.0, _meta()),
                "f1": FeatureCell(11.0, _meta()),
            },
        },
    )

    sample = build_temporal_graph_sample(
        site_id="SITE",
        device_ids=("A", "B"),
        feature_definitions=(
            FeatureDefinition("f1", "unit"),
            FeatureDefinition("f2", "unit"),
        ),
        frames=(frame,),
        adjacency=((0.0, 1.0), (1.0, 0.0)),
        adjacency_method="fixed",
        adjacency_provenance="test",
        target=RegressionTarget(
            device_id="A",
            quantity="future_value",
            unit="unit",
            horizon_s=60.0,
            target_timestamp_utc=t0 + timedelta(seconds=60),
            value=1.0,
            available=True,
            source_kind=MLSourceKind.DERIVED,
            validation_status=MLValidationStatus.VALIDATED,
        ),
    )

    assert sample.feature_names == ("f1", "f2")
    assert sample.feature_values[0] == (
        (11.0, 12.0),
        (21.0, 22.0),
    )


def test_aligned_frame_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        AlignedFeatureFrame(
            datetime(2026, 10, 11, 0, 0),
            {},
        )


def test_feature_cell_rejects_nan():
    with pytest.raises(ValueError, match="finite"):
        FeatureCell(float("nan"), _meta())


def test_feature_cell_none_requires_missing_metadata():
    with pytest.raises(ValueError, match="MISSING_METADATA"):
        FeatureCell(None, _meta())


def test_select_trailing_frames_does_not_interpolate_gaps():
    base = datetime(2026, 10, 11, 0, 0, tzinfo=UTC)

    frames = (
        AlignedFeatureFrame(base, {}),
        AlignedFeatureFrame(base + timedelta(minutes=5), {}),
        AlignedFeatureFrame(base + timedelta(minutes=30), {}),
    )

    selected = select_trailing_frames(
        frames,
        end_index=2,
        window_length=2,
    )

    assert len(selected) == 2
    assert selected[0].timestamp_utc == (
        base + timedelta(minutes=5)
    )
    assert selected[1].timestamp_utc == (
        base + timedelta(minutes=30)
    )


def test_select_trailing_frames_rejects_insufficient_history():
    base = datetime(2026, 10, 11, tzinfo=UTC)

    frames = (
        AlignedFeatureFrame(base, {}),
    )

    with pytest.raises(ValueError, match="insufficient observed frames"):
        select_trailing_frames(
            frames,
            end_index=0,
            window_length=2,
        )


def test_out_of_order_window_is_rejected():
    base = datetime(2026, 10, 11, tzinfo=UTC)

    frames = (
        AlignedFeatureFrame(
            base + timedelta(minutes=10),
            {},
        ),
        AlignedFeatureFrame(
            base + timedelta(minutes=5),
            {},
        ),
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        select_trailing_frames(
            frames,
            end_index=1,
            window_length=2,
        )


def test_site_weather_is_separate_from_node_tensor():
    t0 = datetime(2026, 10, 11, tzinfo=UTC)
    external = FeatureMetadata(
        source_kind=MLSourceKind.EXTERNAL,
        validation_status=MLValidationStatus.NOT_APPLICABLE,
        source_file="Open-Meteo",
    )
    frames = (
        AlignedFeatureFrame(t0, {"ROVER-B1-01": {"ppa_g": FeatureCell(0.0, _meta())}},
                            {"rainfall_24h_external": FeatureCell(12.0, external)}),
        AlignedFeatureFrame(t0 + timedelta(minutes=5), {"ROVER-B1-01": {}}, {}),
    )
    sample = build_temporal_graph_sample(
        site_id="ITB-STAGING-01", device_ids=("ROVER-B1-01",),
        feature_definitions=(FeatureDefinition("ppa_g", "g"),),
        site_context_definitions=(FeatureDefinition("rainfall_24h_external", "mm"),),
        frames=frames, adjacency=((0.0,),), adjacency_method="fixed",
        adjacency_provenance="test", target=_target(frames[-1].timestamp_utc),
    )
    assert sample.device_ids == ("ROVER-B1-01",)
    assert sample.feature_values == (((0.0,),), ((None,),))
    assert sample.site_context_values == ((12.0,), (None,))
    assert sample.site_context_mask == ((True,), (False,))
    assert sample.site_context_metadata[0][0].source_file == "Open-Meteo"
    dense, mask = sample.dense_site_context()
    assert dense == ((12.0,), (0.0,)) and mask == ((True,), (False,))


def test_weather_api_cannot_be_fabricated_as_node():
    t0 = datetime(2026, 10, 11, tzinfo=UTC)
    with pytest.raises(ValueError, match="WEATHER-API"):
        build_temporal_graph_sample(
            site_id="S", device_ids=("WEATHER-API",),
            feature_definitions=(FeatureDefinition("rain", "mm"),),
            frames=(AlignedFeatureFrame(t0, {"WEATHER-API": {}}),),
            adjacency=((0.0,),), adjacency_method="fixed",
            adjacency_provenance="test", target=_target(t0),
        )


def test_undeclared_site_context_is_rejected():
    t0 = datetime(2026, 10, 11, tzinfo=UTC)
    with pytest.raises(ValueError, match="undeclared site context"):
        build_temporal_graph_sample(
            site_id="S", device_ids=("ROVER-B1-01",),
            feature_definitions=(FeatureDefinition("ppa", "g"),),
            frames=(AlignedFeatureFrame(t0, {}, {"rain": FeatureCell(0.0, _meta(MLSourceKind.EXTERNAL))}),),
            adjacency=((0.0,),), adjacency_method="fixed",
            adjacency_provenance="test", target=_target(t0),
        )


def test_non_external_provenance_rejected_in_site_context():
    t0 = datetime(2026, 10, 11, tzinfo=UTC)
    with pytest.raises(ValueError, match="external provenance"):
        build_temporal_graph_sample(
            site_id="S", device_ids=("ROVER-B1-01",),
            feature_definitions=(FeatureDefinition("ppa", "g"),),
            site_context_definitions=(FeatureDefinition("rain", "mm"),),
            frames=(AlignedFeatureFrame(t0, {}, {"rain": FeatureCell(1.0, _meta())}),),
            adjacency=((0.0,),), adjacency_method="fixed",
            adjacency_provenance="test", target=_target(t0),
        )
