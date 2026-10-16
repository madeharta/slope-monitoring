"""ModelRegistry — blueprint §8 (weight lifecycle) + §3.4 (switch-architecture).

Hard rule from the approved blueprint, restated as code-level invariants
below: NEVER read weights from disk inside `predict()`; a failed
`compatibility_check` must NEVER mutate `_active_model`; `rollback()` must
restore the exact previous instance, not merely the previous version_id.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from common.errors import ModelIncompatibleError, ModelTypeUnavailableError, NotFoundError
from ml.domain.canonical_schema import Displacement  # noqa: F401  (re-exported for callers)
from ml.domain.interfaces import GraphBatch, ModelInterface, PredictionResult
from ml.registry.model_factory import ModelFactory, ModelNotImplementedError, UnknownModelTypeError


@dataclass
class RegisteredVersion:
    version_id: str
    model_type: str
    artifact_path: str
    status: str  # 'registered' | 'rejected' | 'active' | 'retired' — mirrors data/db model_versions
    registered_at: datetime
    activated_at: datetime | None = None


class ModelRegistry:
    """One process-wide instance, constructed once at app startup and
    injected into routers via apps/api/dependencies.py — never instantiated
    per-request."""

    def __init__(self) -> None:
        self._versions: dict[str, RegisteredVersion] = {}
        self._active_model: ModelInterface | None = None
        self._active_version: RegisteredVersion | None = None
        self._previous_model: ModelInterface | None = None
        self._previous_version: RegisteredVersion | None = None
        self._lock = threading.RLock()

    # --- Registration -------------------------------------------------

    def register_version(self, model_type: str, version_id: str, artifact_path: str) -> RegisteredVersion:
        rv = RegisteredVersion(
            version_id=version_id,
            model_type=model_type,
            artifact_path=artifact_path,
            status="registered",
            registered_at=datetime.now(timezone.utc),
        )
        self._versions[version_id] = rv
        return rv

    # --- Compatibility check (§8.2) ------------------------------------

    @staticmethod
    def _create_model(model_type: str) -> ModelInterface:
        """Wraps ModelFactory.create() — converts the plain
        NotImplementedError/ValueError subclasses it raises into an
        AppError (ModelTypeUnavailableError), so the response goes through
        the proven-working AppError dispatch path instead of relying on a
        separate global exception_handler registration (see class
        docstring on ModelTypeUnavailableError for why)."""
        try:
            return ModelFactory.create(model_type)
        except (ModelNotImplementedError, UnknownModelTypeError) as exc:
            raise ModelTypeUnavailableError(str(exc)) from exc

    def compatibility_check(self, version_id: str, expected_n_features: int) -> None:
        """Raises ModelIncompatibleError on mismatch. MUST be called before
        activate(); activate() calls this itself so a caller cannot skip it."""
        rv = self._versions.get(version_id)
        if rv is None:
            raise NotFoundError("model version", version_id)

        candidate = self._create_model(rv.model_type)
        contract = candidate.input_contract()
        if contract.get("n_features") != expected_n_features:
            rv.status = "rejected"
            raise ModelIncompatibleError(
                rv.model_type, version_id,
                f"expects {contract.get('n_features')} features, pipeline provides {expected_n_features}",
            )

    # --- Hot-reload activation (§8.2 / §3.4) ---------------------------

    def activate(self, version_id: str, expected_n_features: int) -> None:
        """Atomic swap. Raises (and does NOT mutate active state) if the
        version is unknown, unimplemented, or fails compatibility_check —
        this is the invariant a naive reimplementation most often breaks."""
        with self._lock:
            rv = self._versions.get(version_id)
            if rv is None:
                raise NotFoundError("model version", version_id)

            self.compatibility_check(version_id, expected_n_features)  # raises on failure, nothing mutated yet

            candidate = self._create_model(rv.model_type)
            candidate.load_weights(version_id, rv.artifact_path)  # raises if artifact missing — still before any swap

            # Only past this point do we touch shared state.
            self._previous_model, self._previous_version = self._active_model, self._active_version
            self._active_model, self._active_version = candidate, rv
            rv.status = "active"
            rv.activated_at = datetime.now(timezone.utc)

    # --- Inference (§8.2 — zero request-time disk I/O) ------------------

    def predict(self, batch: GraphBatch) -> PredictionResult:
        with self._lock:
            model = self._active_model
        if model is None:
            raise NotFoundError("active model", "<none activated>")
        return model.predict(batch)  # reads in-memory weights only

    # --- Rollback (§8.2) -------------------------------------------------

    def rollback(self) -> RegisteredVersion:
        with self._lock:
            if self._previous_model is None:
                raise NotFoundError("previous model", "<no prior activation to roll back to>")
            self._active_model, self._previous_model = self._previous_model, self._active_model
            self._active_version, self._previous_version = self._previous_version, self._active_version
            self._active_version.status = "active"
            return self._active_version

    # --- Introspection (for apps/api/routers/v1/model_ops.py) -----------

    def active_summary(self) -> dict | None:
        with self._lock:
            if self._active_version is None:
                return None
            return {
                "model_type": self._active_version.model_type,
                "version_id": self._active_version.version_id,
                "activated_at": self._active_version.activated_at,
            }
