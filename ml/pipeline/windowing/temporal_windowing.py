"""Temporal window assembly for ml.dataset.v1.

This module deliberately does NOT:
- resample;
- interpolate;
- forward-fill;
- back-fill;
- infer missing sensor values.

Callers provide observed/aligned timestamps. Missing cells remain explicit
None + mask=False.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Mapping, Optional, Sequence

from ml.domain.dataset_schema import (
    DATASET_SCHEMA_VERSION,
    FeatureDefinition,
    FeatureMetadata,
    MISSING_METADATA,
    RegressionTarget,
    TemporalGraphSample,
    require_aware_datetime,
)


@dataclass(frozen=True)
class FeatureCell:
    value: Optional[float]
    metadata: FeatureMetadata

    def __post_init__(self) -> None:
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("FeatureCell value must be finite")

        if self.value is None:
            if self.metadata != MISSING_METADATA:
                raise ValueError(
                    "FeatureCell value=None must use MISSING_METADATA"
                )
        elif self.metadata == MISSING_METADATA:
            raise ValueError(
                "numeric FeatureCell cannot use MISSING_METADATA"
            )

    @property
    def available(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class AlignedFeatureFrame:
    """One observed timestamp.

    values:
        device_id -> feature_name -> FeatureCell

    Missing mappings mean unavailable data; they do not mean physical zero.
    """

    timestamp_utc: datetime
    values: Mapping[str, Mapping[str, FeatureCell]]

    def __post_init__(self) -> None:
        require_aware_datetime(
            self.timestamp_utc,
            "AlignedFeatureFrame.timestamp_utc",
        )


def select_trailing_frames(
    frames: Sequence[AlignedFeatureFrame],
    *,
    end_index: int,
    window_length: int,
) -> tuple[AlignedFeatureFrame, ...]:
    """Select observed frames only, without synthesizing intermediate rows."""

    if window_length <= 0:
        raise ValueError("window_length must be > 0")

    if end_index < 0 or end_index >= len(frames):
        raise IndexError("end_index out of range")

    start_index = end_index - window_length + 1

    if start_index < 0:
        raise ValueError(
            "insufficient observed frames for requested window_length"
        )

    selected = tuple(frames[start_index : end_index + 1])

    for previous, current in zip(selected, selected[1:]):
        if current.timestamp_utc <= previous.timestamp_utc:
            raise ValueError(
                "selected frame timestamps must be strictly increasing"
            )

    return selected


def build_temporal_graph_sample(
    *,
    site_id: str,
    device_ids: Sequence[str],
    feature_definitions: Sequence[FeatureDefinition],
    frames: Sequence[AlignedFeatureFrame],
    adjacency: Sequence[Sequence[float]],
    adjacency_method: str,
    adjacency_provenance: str,
    target: RegressionTarget,
) -> TemporalGraphSample:
    """Build one canonical temporal graph sample without fabricating data."""

    if not frames:
        raise ValueError("frames must not be empty")

    ordered_devices = tuple(device_ids)
    ordered_definitions = tuple(feature_definitions)
    ordered_feature_names = tuple(
        definition.name for definition in ordered_definitions
    )

    values_by_time = []
    mask_by_time = []
    metadata_by_time = []

    for frame in frames:
        timestep_values = []
        timestep_mask = []
        timestep_metadata = []

        for device_id in ordered_devices:
            device_values = frame.values.get(device_id, {})

            node_values = []
            node_mask = []
            node_metadata = []

            for feature_name in ordered_feature_names:
                cell = device_values.get(feature_name)

                if cell is None:
                    node_values.append(None)
                    node_mask.append(False)
                    node_metadata.append(MISSING_METADATA)
                    continue

                node_values.append(cell.value)
                node_mask.append(cell.available)
                node_metadata.append(cell.metadata)

            timestep_values.append(tuple(node_values))
            timestep_mask.append(tuple(node_mask))
            timestep_metadata.append(tuple(node_metadata))

        values_by_time.append(tuple(timestep_values))
        mask_by_time.append(tuple(timestep_mask))
        metadata_by_time.append(tuple(timestep_metadata))

    return TemporalGraphSample(
        schema_version=DATASET_SCHEMA_VERSION,
        site_id=site_id,
        device_ids=ordered_devices,
        feature_definitions=ordered_definitions,
        timestamps_utc=tuple(
            frame.timestamp_utc for frame in frames
        ),
        feature_values=tuple(values_by_time),
        feature_mask=tuple(mask_by_time),
        feature_metadata=tuple(metadata_by_time),
        adjacency=tuple(
            tuple(float(value) for value in row)
            for row in adjacency
        ),
        adjacency_method=adjacency_method,
        adjacency_provenance=adjacency_provenance,
        target=target,
    )
