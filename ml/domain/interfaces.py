from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
@dataclass(frozen=True)
class GraphBatch:
    device_ids: list[str]
    node_features: list[list[float]]
    adjacency: list[list[float]]
    window_length: int
@dataclass(frozen=True)
class PredictionResult:
    device_ids: list[str]
    risk_scores: list[float]
    model_type: str
    version_id: str
class ModelInterface(ABC):
    @abstractmethod
    def load_weights(self, version_id: str, artifact_path: str) -> None:
        ...
    @abstractmethod
    def predict(self, batch: GraphBatch) -> PredictionResult: ...
    @abstractmethod
    def input_contract(self) -> dict:
        ...
    @property
    @abstractmethod
    def model_type(self) -> str: ...
