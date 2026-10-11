"""Canonical real-data ML dataset contract.

Architecture boundary:
    persisted/canonical field data
        -> ml.dataset.v1
        -> model-specific adapters (GCN/GAT)

This module intentionally has no DB, NumPy, Torch, or model dependency.

Hard rules:
- missing != physical zero;
- missing values are represented by None + mask=False;
- NaN/Inf are rejected;
- timestamps are timezone-aware and strictly increasing;
- feature identity includes an explicit unit;
- quality/provenance/validation metadata remain attached to each feature cell;
- prediction targets are explicitly future-facing;
- dense tensor conversion can only happen together with the availability mask.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Optional


DATASET_SCHEMA_VERSION = "ml.dataset.v1"


class MLSourceKind(str, Enum):
    """Dataset-level provenance vocabulary.

    DEVICE / EXTERNAL / DERIVED map to persisted measurement semantics.
    MISSING exists ONLY inside the ML dataset layer and MUST NOT be written
    back to the measurements table.
    """

    DEVICE = "device"
    EXTERNAL = "external"
    DERIVED = "derived"
    MISSING = "missing"


class MLValidationStatus(str, Enum):
    """Superset required by current persisted + QA data paths.

    `unvalidated` is needed for PPK QA records.
    `missing` is dataset-only.
    """

    UNVERIFIED = "unverified"
    PROVISIONAL = "provisional"
    VALIDATED = "validated"
    NOT_APPLICABLE = "not_applicable"
    UNVALIDATED = "unvalidated"
    MISSING = "missing"


def require_aware_datetime(dt: datetime, field_name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


@dataclass(frozen=True)
class FeatureDefinition:
    """Stable identity of one model feature."""

    name: str
    unit: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("feature name must not be empty")
        if not self.unit:
            raise ValueError("feature unit must not be empty")


@dataclass(frozen=True)
class FeatureMetadata:
    """Per-cell provenance and quality context."""

    source_kind: MLSourceKind
    validation_status: MLValidationStatus
    quality_flag: str | None = None
    source_file: str | None = None

    def __post_init__(self) -> None:
        if (
            self.source_kind is MLSourceKind.MISSING
            and self.validation_status is not MLValidationStatus.MISSING
        ):
            raise ValueError(
                "missing source_kind requires missing validation_status"
            )

        if (
            self.validation_status is MLValidationStatus.MISSING
            and self.source_kind is not MLSourceKind.MISSING
        ):
            raise ValueError(
                "missing validation_status requires missing source_kind"
            )


MISSING_METADATA = FeatureMetadata(
    source_kind=MLSourceKind.MISSING,
    validation_status=MLValidationStatus.MISSING,
    quality_flag="missing",
)


@dataclass(frozen=True)
class RegressionTarget:
    """Future regression target for one device and quantity."""

    device_id: str
    quantity: str
    unit: str
    horizon_s: float
    target_timestamp_utc: datetime
    value: Optional[float]
    available: bool
    source_kind: MLSourceKind
    validation_status: MLValidationStatus
    provenance_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("target device_id must not be empty")
        if not self.quantity:
            raise ValueError("target quantity must not be empty")
        if not self.unit:
            raise ValueError("target unit must not be empty")

        require_aware_datetime(
            self.target_timestamp_utc,
            "target_timestamp_utc",
        )

        require_finite(self.horizon_s, "horizon_s")
        if self.horizon_s <= 0:
            raise ValueError("horizon_s must be > 0")

        if self.available:
            if self.value is None:
                raise ValueError("available target must have a value")
            require_finite(self.value, "target value")
        elif self.value is not None:
            raise ValueError("unavailable target must have value=None")

        if self.source_kind is MLSourceKind.MISSING:
            raise ValueError(
                "target source_kind cannot be missing; unavailable target "
                "still needs provenance describing why it is unavailable"
            )

        if self.validation_status is MLValidationStatus.MISSING:
            raise ValueError(
                "target validation_status cannot be missing"
            )


@dataclass(frozen=True)
class TemporalGraphSample:
    """One supervised or not-yet-labeled temporal graph sample.

    Shapes:
      feature_values   [T][N][F] float | None
      feature_mask     [T][N][F] bool
      feature_metadata [T][N][F] FeatureMetadata
      adjacency        [N][N] float

    No cadence is assumed here. Irregular timestamp gaps remain visible.
    """

    schema_version: str
    site_id: str
    device_ids: tuple[str, ...]
    feature_definitions: tuple[FeatureDefinition, ...]
    timestamps_utc: tuple[datetime, ...]

    feature_values: tuple[
        tuple[
            tuple[Optional[float], ...],
            ...,
        ],
        ...,
    ]

    feature_mask: tuple[
        tuple[
            tuple[bool, ...],
            ...,
        ],
        ...,
    ]

    feature_metadata: tuple[
        tuple[
            tuple[FeatureMetadata, ...],
            ...,
        ],
        ...,
    ]

    adjacency: tuple[tuple[float, ...], ...]
    adjacency_method: str
    adjacency_provenance: str
    target: RegressionTarget

    # Optional site-wide covariates. Legacy node-only constructors remain valid.
    site_context_definitions: tuple[FeatureDefinition, ...] = ()
    site_context_values: tuple[tuple[Optional[float], ...], ...] = ()
    site_context_mask: tuple[tuple[bool, ...], ...] = ()
    site_context_metadata: tuple[tuple[FeatureMetadata, ...], ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != DATASET_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {DATASET_SCHEMA_VERSION!r}"
            )

        if not self.site_id:
            raise ValueError("site_id must not be empty")

        if not self.device_ids:
            raise ValueError("device_ids must not be empty")
        if len(set(self.device_ids)) != len(self.device_ids):
            raise ValueError("device_ids must be unique")

        if not self.feature_definitions:
            raise ValueError("feature_definitions must not be empty")

        if any(device.upper() == "WEATHER-API" for device in self.device_ids):
            raise ValueError("WEATHER-API is site context, not a graph node")

        names = tuple(f.name for f in self.feature_definitions)
        if len(set(names)) != len(names):
            raise ValueError("feature names must be unique")

        if not self.timestamps_utc:
            raise ValueError("timestamps_utc must not be empty")

        previous: datetime | None = None
        for ts in self.timestamps_utc:
            require_aware_datetime(ts, "timestamps_utc item")

            if previous is not None and ts <= previous:
                raise ValueError(
                    "timestamps_utc must be strictly increasing"
                )

            previous = ts

        t_count = len(self.timestamps_utc)
        n_count = len(self.device_ids)
        f_count = len(self.feature_definitions)

        self._validate_3d_shape(
            self.feature_values,
            t_count,
            n_count,
            f_count,
            "feature_values",
        )
        self._validate_3d_shape(
            self.feature_mask,
            t_count,
            n_count,
            f_count,
            "feature_mask",
        )
        self._validate_3d_shape(
            self.feature_metadata,
            t_count,
            n_count,
            f_count,
            "feature_metadata",
        )

        for t_idx in range(t_count):
            for n_idx in range(n_count):
                for f_idx in range(f_count):
                    value = self.feature_values[t_idx][n_idx][f_idx]
                    available = self.feature_mask[t_idx][n_idx][f_idx]
                    metadata = self.feature_metadata[t_idx][n_idx][f_idx]

                    if available:
                        if value is None:
                            raise ValueError(
                                "feature_mask=True requires a numeric value"
                            )

                        require_finite(value, "feature value")

                        if metadata.source_kind is MLSourceKind.MISSING:
                            raise ValueError(
                                "available feature cannot use missing metadata"
                            )

                    else:
                        if value is not None:
                            raise ValueError(
                                "feature_mask=False requires feature value=None"
                            )

                        if metadata.source_kind is not MLSourceKind.MISSING:
                            raise ValueError(
                                "missing feature must use missing metadata"
                            )

        self._validate_site_context(t_count)

        if len(self.adjacency) != n_count:
            raise ValueError("adjacency must have N rows")

        for row in self.adjacency:
            if len(row) != n_count:
                raise ValueError("adjacency must have shape [N][N]")

            for weight in row:
                require_finite(weight, "adjacency weight")

                if weight < 0:
                    raise ValueError(
                        "adjacency weights must be non-negative"
                    )

        if not self.adjacency_method:
            raise ValueError("adjacency_method must not be empty")

        if not self.adjacency_provenance:
            raise ValueError("adjacency_provenance must not be empty")

        if self.target.device_id not in self.device_ids:
            raise ValueError("target device_id must exist in device_ids")

        window_end = self.timestamps_utc[-1]

        if self.target.target_timestamp_utc <= window_end:
            raise ValueError(
                "target timestamp must be strictly after input window"
            )

        observed_horizon = (
            self.target.target_timestamp_utc - window_end
        ).total_seconds()

        if not math.isclose(
            observed_horizon,
            self.target.horizon_s,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "target horizon does not match target timestamp - window end"
            )

    def _validate_site_context(self, t_count: int) -> None:
        c_count = len(self.site_context_definitions)
        names = tuple(d.name for d in self.site_context_definitions)
        if len(names) != len(set(names)):
            raise ValueError("site context feature names must be unique")
        if not c_count and not any((
            self.site_context_values, self.site_context_mask,
            self.site_context_metadata,
        )):
            return  # Backward-compatible node-only sample.
        for field_name, matrix in (
            ("site_context_values", self.site_context_values),
            ("site_context_mask", self.site_context_mask),
            ("site_context_metadata", self.site_context_metadata),
        ):
            if len(matrix) != t_count or any(len(row) != c_count for row in matrix):
                raise ValueError(f"{field_name} must have shape [T][C]")
        for values, masks, metas in zip(
            self.site_context_values, self.site_context_mask,
            self.site_context_metadata,
        ):
            for value, available, meta in zip(values, masks, metas):
                if type(available) is not bool or not isinstance(meta, FeatureMetadata):
                    raise ValueError("invalid site context mask or metadata")
                if available:
                    if value is None:
                        raise ValueError("available site context requires numeric value")
                    require_finite(value, "site context value")
                    if meta.source_kind is not MLSourceKind.EXTERNAL:
                        raise ValueError("site context requires external provenance")
                elif value is not None or meta.source_kind is not MLSourceKind.MISSING:
                    raise ValueError("missing site context requires None and missing metadata")

    def dense_site_context(self, *, fill_value: float = 0.0):
        """Return dense site context and its mandatory availability mask."""
        require_finite(fill_value, "fill_value")
        return (
            tuple(tuple(v if m else fill_value for v, m in zip(row, mask))
                  for row, mask in zip(self.site_context_values, self.site_context_mask)),
            self.site_context_mask,
        )

    @staticmethod
    def _validate_3d_shape(
        value,
        t_count: int,
        n_count: int,
        f_count: int,
        field_name: str,
    ) -> None:
        if len(value) != t_count:
            raise ValueError(f"{field_name} must have T={t_count}")

        for timestep in value:
            if len(timestep) != n_count:
                raise ValueError(
                    f"{field_name} must have N={n_count} per timestep"
                )

            for node in timestep:
                if len(node) != f_count:
                    raise ValueError(
                        f"{field_name} must have F={f_count} per node"
                    )

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.feature_definitions)

    @property
    def feature_units(self) -> tuple[str, ...]:
        return tuple(f.unit for f in self.feature_definitions)

    @property
    def window_start_utc(self) -> datetime:
        return self.timestamps_utc[0]

    @property
    def window_end_utc(self) -> datetime:
        return self.timestamps_utc[-1]

    def dense_features(
        self,
        *,
        fill_value: float = 0.0,
    ) -> tuple[
        tuple[tuple[tuple[float, ...], ...], ...],
        tuple[tuple[tuple[bool, ...], ...], ...],
    ]:
        """Explicit dense-tensor boundary.

        Dense numeric tensors require a fill value, but the mask is always
        returned with the dense values. A caller that discards the mask would
        violate the ml.dataset.v1 contract.
        """

        require_finite(fill_value, "fill_value")

        dense = tuple(
            tuple(
                tuple(
                    value if available else fill_value
                    for value, available in zip(
                        node_values,
                        node_mask,
                    )
                )
                for node_values, node_mask in zip(
                    timestep_values,
                    timestep_mask,
                )
            )
            for timestep_values, timestep_mask in zip(
                self.feature_values,
                self.feature_mask,
            )
        )

        return dense, self.feature_mask
