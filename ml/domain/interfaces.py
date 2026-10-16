"""ModelInterface — blueprint §3.1. Every architecture (GCN, temporal,
ST-GCN, ST-GAT) implements this and nothing else is imported by apps/api."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GraphBatch:
    """Tensor-ready input. Kept as a plain dataclass (not a torch object)
    here so this module has zero torch dependency; concrete models convert
    it to tensors internally."""

    device_ids: list[str]
    node_features: list[list[float]]   # (N, F) — see ml/pipeline/graph_builder
    adjacency: list[list[float]]       # (N, N) — see blueprint §6
    window_length: int


@dataclass(frozen=True)
class PredictionResult:
    device_ids: list[str]
    risk_scores: list[float]           # per-node, 2-class model per project convention
    model_type: str
    version_id: str


class ModelInterface(ABC):
    @abstractmethod
    def load_weights(self, version_id: str, artifact_path: str) -> None:
        """REVISED 2026-09-19 (item 11 gap fix): `artifact_path` added.
        Previously only `version_id` (a bare string) was passed — no
        concrete model had any reliable way to find its checkpoint FILE on
        disk from that alone (ModelRegistry held `artifact_path` in
        `RegisteredVersion` but never passed it through). Every
        implementation MUST use `artifact_path` to locate its checkpoint —
        do not hardcode a fixed path (that was the exact bug this fixes,
        see ml/legacy/gcn_v2_6_0/model_v2_6_0.py's history)."""
        ...

    @abstractmethod
    def predict(self, batch: GraphBatch) -> PredictionResult: ...

    @abstractmethod
    def input_contract(self) -> dict:
        """Shape/feature contract used by ModelRegistry.compatibility_check
        (§8.2) — MUST be pure/side-effect-free, callable before load_weights."""
        ...

    @property
    @abstractmethod
    def model_type(self) -> str: ...
