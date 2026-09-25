from __future__ import annotations
from ml.domain.interfaces import GraphBatch, ModelInterface, PredictionResult
class GCNBaseline(ModelInterface):
    def __init__(self) -> None:
        self._loaded_version: str | None = None
    @property
    def model_type(self) -> str:
        return "gcn"
    def input_contract(self) -> dict:
        return {"n_features": 15, "n_classes": 2, "supports_variable_n": True}
    def load_weights(self, version_id: str, artifact_path: str) -> None:
        self._loaded_version = version_id
    def predict(self, batch: GraphBatch) -> PredictionResult:
        if self._loaded_version is None:
            raise RuntimeError("predict() called before load_weights() — registry bug, not caller error")
        scores = [0.0 for _ in batch.device_ids]
        return PredictionResult(
            device_ids=batch.device_ids,
            risk_scores=scores,
            model_type=self.model_type,
            version_id=self._loaded_version,
        )
