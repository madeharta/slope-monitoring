from __future__ import annotations
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from common.errors import ModelIncompatibleError, ModelTypeUnavailableError, NotFoundError
from ml.domain.canonical_schema import Displacement
from ml.domain.interfaces import GraphBatch, ModelInterface, PredictionResult
from ml.registry.model_factory import ModelFactory, ModelNotImplementedError, UnknownModelTypeError
@dataclass
class RegisteredVersion:
    version_id: str
    model_type: str
    artifact_path: str
    status: str
    registered_at: datetime
    activated_at: datetime | None = None
class ModelRegistry:
    def __init__(self) -> None:
        self._versions: dict[str, RegisteredVersion] = {}
        self._active_model: ModelInterface | None = None
        self._active_version: RegisteredVersion | None = None
        self._previous_model: ModelInterface | None = None
        self._previous_version: RegisteredVersion | None = None
        self._lock = threading.RLock()
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
    @staticmethod
    def _create_model(model_type: str) -> ModelInterface:
        try:
            return ModelFactory.create(model_type)
        except (ModelNotImplementedError, UnknownModelTypeError) as exc:
            raise ModelTypeUnavailableError(str(exc)) from exc
    def compatibility_check(self, version_id: str, expected_n_features: int) -> None:
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
    def activate(self, version_id: str, expected_n_features: int) -> None:
        with self._lock:
            rv = self._versions.get(version_id)
            if rv is None:
                raise NotFoundError("model version", version_id)
            self.compatibility_check(version_id, expected_n_features)
            candidate = self._create_model(rv.model_type)
            candidate.load_weights(version_id, rv.artifact_path)
            self._previous_model, self._previous_version = self._active_model, self._active_version
            self._active_model, self._active_version = candidate, rv
            rv.status = "active"
            rv.activated_at = datetime.now(timezone.utc)
    def predict(self, batch: GraphBatch) -> PredictionResult:
        with self._lock:
            model = self._active_model
        if model is None:
            raise NotFoundError("active model", "<none activated>")
        return model.predict(batch)
    def rollback(self) -> RegisteredVersion:
        with self._lock:
            if self._previous_model is None:
                raise NotFoundError("previous model", "<no prior activation to roll back to>")
            self._active_model, self._previous_model = self._previous_model, self._active_model
            self._active_version, self._previous_version = self._previous_version, self._active_version
            self._active_version.status = "active"
            return self._active_version
    def active_summary(self) -> dict | None:
        with self._lock:
            if self._active_version is None:
                return None
            return {
                "model_type": self._active_version.model_type,
                "version_id": self._active_version.version_id,
                "activated_at": self._active_version.activated_at,
            }
