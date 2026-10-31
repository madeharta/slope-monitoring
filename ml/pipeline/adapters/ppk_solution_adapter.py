"""Read-only PPK solution -> ML candidate boundary (not target approval).

A technical quality-gate pass is not geodetic validation.  No record emitted
by this module is a supervised ground-truth label, regardless of DB statuses.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping, Sequence
import math
import re

from ml.domain.dataset_schema import require_aware_datetime
# Locked contract values from ppk_engine.py and ppk_solution_repository.py.
# Kept dependency-free so ML adapters do not import operational RTKLIB modules.
PPK_OUTPUT_SCHEMA_VERSION = "ppk.solution.v1"
PPK_VERTICAL_DATUM = "ELLIPSOIDAL_WGS84"

HASH_FIELDS = (
    "navigation_sha256", "base_rawx_sha256", "rover_rawx_sha256",
    "base_obs_sha256", "rover_obs_sha256", "normalized_navigation_sha256",
    "convbin_sha256", "rnx2rtkp_sha256", "solution_pos_sha256",
)
OPTIONAL_HASH_FIELDS = ("rtklib_config_sha256",)
FLOAT_FIELDS = (
    "latitude", "longitude", "ellipsoidal_height_m",
    "displacement_e_mm", "displacement_n_mm", "displacement_u_mm",
    "displacement_total_mm", "h_acc_m", "rtklib_sdn_m", "rtklib_sde_m",
    "rtklib_sdu_m",
)
OPTIONAL_FLOAT_FIELDS = ("rtklib_age_s", "rtklib_ratio")
REQUIRED = frozenset((
    "time", "processed_at", "site_id", "base_device_id", "rover_device_id",
    "schema_version", "vertical_datum", "processing_engine", "quality_gate_status",
    "validation_status", "rtklib_quality", "rtklib_ns", *FLOAT_FIELDS,
    *HASH_FIELDS,
))
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class PPKCandidate:
    site_id: str
    base_device_id: str
    rover_device_id: str
    observed_at_utc: datetime
    processed_at_utc: datetime
    schema_version: str
    vertical_datum: str
    displacements_mm: tuple[float, float, float, float]
    quality_gate_status: str
    validation_status: str
    rtklib_quality: int
    rtklib_ns: int
    hashes: tuple[tuple[str, str | None], ...]
    provenance_status: str  # complete | partial
    technical_quality_pass: bool
    structurally_valid: bool
    supervised_target_eligible: bool  # Always false in Batch 2C
    eligibility_reason: str


@dataclass(frozen=True)
class PPKAudit:
    candidates: tuple[PPKCandidate, ...]
    rejected: tuple[tuple[int, str], ...]
    total: int


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be datetime")
    require_aware_datetime(value, field)
    return value.astimezone(timezone.utc)


def _finite(value: object, field: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{field} must be finite numeric")
    if nonnegative and value < 0:
        raise ValueError(f"{field} must be nonnegative")
    return float(value)


def adapt_ppk_solution(record: Mapping[str, object], *, site_id: str,
                       rover_ids: Sequence[str], base_device_id: str) -> PPKCandidate:
    """Fail closed on malformed records; preserve partial provenance explicitly.

    Note: `validated` from DB is retained but is NOT sufficient evidence for
    supervised-target approval. That approval requires a separate policy.
    """
    if not isinstance(record, Mapping):
        raise ValueError("PPK solution must be mapping")
    if not isinstance(site_id, str) or not site_id.strip():
        raise ValueError("invalid expected site_id")
    if not isinstance(base_device_id, str) or not base_device_id.strip():
        raise ValueError("invalid expected base_device_id")
    if not rover_ids or len(set(rover_ids)) != len(rover_ids) or base_device_id in rover_ids:
        raise ValueError("invalid rover_ids")
    if not all(isinstance(x, str) and x.strip() for x in rover_ids):
        raise ValueError("invalid rover_ids")
    absent = REQUIRED.difference(record.keys())
    if absent:
        raise ValueError(f"missing PPK columns: {sorted(absent)}")
    if record["site_id"] != site_id or record["base_device_id"] != base_device_id:
        raise ValueError("PPK site/base identity mismatch")
    if record["rover_device_id"] not in rover_ids:
        raise ValueError("PPK rover identity mismatch")
    if record["schema_version"] != PPK_OUTPUT_SCHEMA_VERSION:
        raise ValueError("invalid PPK schema version")
    if record["vertical_datum"] != PPK_VERTICAL_DATUM:
        raise ValueError("invalid PPK vertical datum")
    if record["processing_engine"] != "RTKLIB":
        raise ValueError("invalid PPK processing engine")
    gate = record["quality_gate_status"]
    validation = record["validation_status"]
    if gate not in ("accepted", "rejected"):
        raise ValueError("invalid PPK quality gate status")
    if validation not in ("unvalidated", "validated"):
        raise ValueError("invalid PPK validation status")
    obs = _utc(record["time"], "time")
    processed = _utc(record["processed_at"], "processed_at")
    # Do not reject a small negative clock skew here: as-of policy must check
    # availability and independently characterize skew before training.
    vals = {f: _finite(record[f], f, nonnegative=f in (
        "h_acc_m", "rtklib_sdn_m", "rtklib_sde_m", "rtklib_sdu_m")) for f in FLOAT_FIELDS}
    if not -90 <= vals["latitude"] <= 90 or not -180 <= vals["longitude"] <= 180:
        raise ValueError("invalid PPK coordinate range")
    for f in OPTIONAL_FLOAT_FIELDS:
        if f in record and record[f] is not None:
            # RTKLIB differential age is signed; retain valid negative values.
            _finite(record[f], f)
    q, ns = record["rtklib_quality"], record["rtklib_ns"]
    if isinstance(q, bool) or not isinstance(q, int) or not 1 <= q <= 6:
        raise ValueError("invalid RTKLIB quality")
    if isinstance(ns, bool) or not isinstance(ns, int) or ns < 0:
        raise ValueError("invalid RTKLIB satellite count")
    hashes = []
    for field in (*HASH_FIELDS, *OPTIONAL_HASH_FIELDS):
        value = record.get(field)
        if value is not None and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
            raise ValueError(f"invalid PPK provenance hash: {field}")
        if field == "navigation_sha256" and value is None:
            raise ValueError("missing required navigation hash")
        hashes.append((field, value))
    complete = all(record.get(field) is not None for field in HASH_FIELDS)
    return PPKCandidate(
        site_id=site_id, base_device_id=base_device_id,
        rover_device_id=record["rover_device_id"],
        observed_at_utc=obs, processed_at_utc=processed,
        schema_version=PPK_OUTPUT_SCHEMA_VERSION, vertical_datum=PPK_VERTICAL_DATUM,
        displacements_mm=tuple(vals[f] for f in (
            "displacement_e_mm", "displacement_n_mm", "displacement_u_mm", "displacement_total_mm")),
        quality_gate_status=gate, validation_status=validation,
        rtklib_quality=q, rtklib_ns=ns, hashes=tuple(hashes),
        provenance_status="complete" if complete else "partial",
        technical_quality_pass=gate == "accepted",
        structurally_valid=True, supervised_target_eligible=False,
        eligibility_reason="independent geodetic and target-policy acceptance pending",
    )


def audit_ppk_solutions(records: Sequence[Mapping[str, object]], **kwargs: object) -> PPKAudit:
    """Deterministic census: reject duplicate solution identities, never overwrite."""
    accepted: list[PPKCandidate] = []
    rejected: list[tuple[int, str]] = []
    seen: set[tuple[str, datetime, str]] = set()
    for i, row in enumerate(records):
        try:
            candidate = adapt_ppk_solution(row, **kwargs)
            key = (candidate.rover_device_id, candidate.observed_at_utc, candidate.schema_version)
            if key in seen:
                raise ValueError("duplicate PPK solution identity")
            seen.add(key)
            accepted.append(candidate)
        except (TypeError, ValueError) as exc:
            rejected.append((i, str(exc)))
    return PPKAudit(tuple(accepted), tuple(rejected), len(records))
