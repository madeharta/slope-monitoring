"""Fail-closed persisted measurements -> ML FeatureCell adapter.

This boundary accepts measurement vocabulary only. PPK solution records and
supervised target approvals must be handled by separate quality gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence
import math

from ml.domain.dataset_schema import (
    FeatureDefinition, FeatureMetadata, MLSourceKind, MLValidationStatus,
    require_aware_datetime,
)
from ml.pipeline.windowing.temporal_windowing import FeatureCell

MEASUREMENT_SOURCE_KINDS = frozenset(("device", "external", "derived"))
MEASUREMENT_VALIDATION_STATUSES = frozenset((
    "unverified", "provisional", "validated", "not_applicable",
))
REQUIRED_FIELDS = frozenset((
    "time", "device_id", "site_id", "quantity", "value", "unit",
    "source_kind", "source_file", "validation_status",
))


@dataclass(frozen=True)
class AdaptedMeasurement:
    site_id: str
    device_id: str
    timestamp_utc: datetime
    definition: FeatureDefinition
    cell: FeatureCell
    scope: str  # node | site
    source_file: str | None
    quality_flag: str | None
    received_at_utc: datetime | None
    availability_status: str  # known | unknown
    quality_status: str  # explicitly_accepted | unknown
    feature_eligibility: str  # candidate_only; NOT approved for training/targets
    provenance_status: str  # complete | partial


@dataclass(frozen=True)
class AdapterAudit:
    accepted: tuple[AdaptedMeasurement, ...]
    rejected: tuple[tuple[int, str], ...]
    total: int

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


def adapt_measurement(
    record: Mapping[str, object],
    *,
    definitions: Mapping[str, FeatureDefinition],
    site_id: str,
    node_ids: Sequence[str],
    external_device_id: str = "WEATHER-API",
    accepted_quality_flags: frozenset[str] = frozenset(),
    require_received_at: bool = False,
    allow_partial_external_provenance: bool = False,
) -> AdaptedMeasurement:
    """Validate one persisted measurement with an explicit quantity/unit policy.

    Quality vocabularies vary by data producer. Caller must explicitly pass
    acceptance flags; unknown non-empty flags fail closed rather than guessed.
    Missing external source_file is rejected by default; explicit audit-only
    opt-in preserves it as partial provenance, never inventing a provider.
    """
    if not isinstance(record, Mapping):
        raise ValueError("measurement must be a mapping")
    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        raise ValueError(f"missing measurement columns: {sorted(missing)}")
    if not isinstance(site_id, str) or not site_id.strip():
        raise ValueError("site_id must not be empty")
    if not isinstance(external_device_id, str) or not external_device_id.strip():
        raise ValueError("external_device_id must not be empty")
    if len(set(node_ids)) != len(node_ids) or external_device_id in node_ids:
        raise ValueError("node_ids must be unique and exclude external source")
    if not all(isinstance(x, str) and x.strip() for x in node_ids):
        raise ValueError("invalid node_ids")
    for field in ("site_id", "device_id", "quantity", "unit"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError(f"{field} must be nonempty string")
    if record["site_id"] != site_id:
        raise ValueError("cross-site measurement")
    quantity = record["quantity"]
    definition = definitions.get(quantity)
    if not isinstance(definition, FeatureDefinition) or definition.name != quantity:
        raise ValueError("undeclared measurement quantity")
    if record["unit"] != definition.unit:
        raise ValueError("measurement unit mismatch")
    source = record["source_kind"]
    validation = record["validation_status"]
    if not isinstance(source, str) or source not in MEASUREMENT_SOURCE_KINDS:
        raise ValueError("invalid persisted measurement source_kind")
    if not isinstance(validation, str) or validation not in MEASUREMENT_VALIDATION_STATUSES:
        raise ValueError("invalid persisted measurement validation_status")
    device = record["device_id"]
    if source == "external":
        if device != external_device_id or validation != "not_applicable":
            raise ValueError("invalid external site context provenance")
        scope = "site"
    else:
        if device not in node_ids or validation == "not_applicable":
            raise ValueError("invalid node measurement identity/validation")
        scope = "node"
    source_file = record["source_file"]
    if source_file is not None and (not isinstance(source_file, str) or not source_file.strip()):
        raise ValueError("invalid source_file")
    if source == "external" and not source_file and not allow_partial_external_provenance:
        raise ValueError("external measurement requires source_file")
    quality = record.get("quality_flag")
    if quality is not None and (not isinstance(quality, str) or not quality.strip()):
        raise ValueError("invalid quality_flag")
    if quality is not None:
        if quality not in accepted_quality_flags:
            raise ValueError("quality_flag not explicitly accepted")
    received_at = record.get("received_at")
    if received_at is not None:
        if not isinstance(received_at, datetime):
            raise ValueError("received_at must be datetime or None")
        require_aware_datetime(received_at, "received_at")
        received_at = received_at.astimezone(timezone.utc)
    elif require_received_at:
        raise ValueError("received_at required for as-of training eligibility")
    timestamp = record["time"]
    if not isinstance(timestamp, datetime):
        raise ValueError("time must be datetime")
    require_aware_datetime(timestamp, "measurement time")
    value = record["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("measurement value must be numeric")
    if not math.isfinite(value):
        raise ValueError("measurement value must be finite")
    metadata = FeatureMetadata(
        source_kind=MLSourceKind(source),
        validation_status=MLValidationStatus(validation),
        source_file=source_file,
        quality_flag=quality,
    )
    return AdaptedMeasurement(
        site_id=site_id, device_id=device, timestamp_utc=timestamp.astimezone(timezone.utc),
        definition=definition, cell=FeatureCell(float(value), metadata),
        scope=scope, source_file=source_file, quality_flag=quality,
        received_at_utc=received_at,
        availability_status="known" if received_at is not None else "unknown",
        quality_status="explicitly_accepted" if quality is not None else "unknown",
        feature_eligibility="candidate_only",
        provenance_status="complete" if source_file is not None else "partial",
    )


def adapt_measurements(
    records: Sequence[Mapping[str, object]], **kwargs: object,
) -> tuple[AdaptedMeasurement, ...]:
    """Reject conflicting duplicates; never silently last-write-wins."""
    result: list[AdaptedMeasurement] = []
    seen: set[tuple[str, str, datetime, str]] = set()
    for record in records:
        item = adapt_measurement(record, **kwargs)
        key = (item.site_id, item.device_id, item.timestamp_utc, item.definition.name)
        if key in seen:
            raise ValueError("duplicate device+timestamp+quantity measurement")
        seen.add(key)
        result.append(item)
    return tuple(result)


def audit_measurements(
    records: Sequence[Mapping[str, object]], **kwargs: object,
) -> AdapterAudit:
    """Read-only, deterministic adapter audit; never rewrites original records.

    Rejections expose index and stable error description, not raw field values.
    Accepted records are candidates only; this does NOT approve training or targets.
    """
    accepted: list[AdaptedMeasurement] = []
    rejected: list[tuple[int, str]] = []
    seen: set[tuple[str, str, datetime, str]] = set()
    for index, record in enumerate(records):
        try:
            item = adapt_measurement(record, **kwargs)
            key = (item.site_id, item.device_id, item.timestamp_utc, item.definition.name)
            if key in seen:
                raise ValueError("duplicate device+timestamp+quantity measurement")
            seen.add(key)
            accepted.append(item)
        except (ValueError, TypeError) as exc:
            rejected.append((index, str(exc)))
    return AdapterAudit(tuple(accepted), tuple(rejected), len(records))
