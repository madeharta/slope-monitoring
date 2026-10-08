from __future__ import annotations
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from ml.domain.interfaces import GraphBatch, ModelInterface, PredictionResult
N_FEATURES = 10
HIDDEN_DIM = 16
def add_self_loops_and_normalize(adjacency: torch.Tensor) -> torch.Tensor:
    n = adjacency.shape[0]
    a_hat = adjacency + torch.eye(n, dtype=adjacency.dtype, device=adjacency.device)
    row_sums = a_hat.sum(dim=1, keepdim=True)
    safe_sums = torch.where(row_sums == 0, torch.ones_like(row_sums), row_sums)
    return a_hat / safe_sums
class GraphConvLayer(nn.Module):
    def __init__(self, in_features: int, out_features: int) -> None:
        super().__init__()
        self.linear = nn.Linear(in_features, out_features)
    def forward(self, x: torch.Tensor, adjacency: torch.Tensor) -> torch.Tensor:
        a_norm = add_self_loops_and_normalize(adjacency)
        return self.linear(a_norm @ x)
class GCNSlopeV1(nn.Module, ModelInterface):
    def __init__(self) -> None:
        nn.Module.__init__(self)
        self.conv1 = GraphConvLayer(N_FEATURES, HIDDEN_DIM)
        self.conv2 = GraphConvLayer(HIDDEN_DIM, 2)
        self._loaded_version: str | None = None
    @property
    def model_type(self) -> str:
        return "gcn_slope_v1"
    def input_contract(self) -> dict:
        return {"n_features": N_FEATURES, "n_classes": 2, "supports_variable_n": True}
    def load_weights(self, version_id: str, artifact_path: str) -> None:
        if not os.path.exists(artifact_path):
            raise FileNotFoundError(f"checkpoint tidak ditemukan: {artifact_path}")
        state_dict = torch.load(artifact_path, map_location="cpu")
        self.load_state_dict(state_dict)
        self._loaded_version = version_id
    def initialize_random_weights(self, seed: int = 42) -> None:
        torch.manual_seed(seed)
        self.conv1 = GraphConvLayer(N_FEATURES, HIDDEN_DIM)
        self.conv2 = GraphConvLayer(HIDDEN_DIM, 2)
        self._loaded_version = f"random-init-seed-{seed}-NOT-FOR-PRODUCTION"
    def predict(self, batch: GraphBatch) -> PredictionResult:
        if self._loaded_version is None:
            raise RuntimeError("predict() called before load_weights() — registry bug, not caller error")
        x = torch.tensor(batch.node_features, dtype=torch.float32)
        adjacency = torch.tensor(batch.adjacency, dtype=torch.float32)
        if x.shape[1] != N_FEATURES:
            raise ValueError(f"node_features punya {x.shape[1]} fitur, model ini butuh {N_FEATURES}")
        self.eval()
        with torch.no_grad():
            h1 = F.relu(self.conv1(x, adjacency))
            h2 = torch.sigmoid(self.conv2(h1, adjacency))
        risk_scores = h2[:, 1].tolist()
        return PredictionResult(
            device_ids=batch.device_ids,
            risk_scores=risk_scores,
            model_type=self.model_type,
            version_id=self._loaded_version,
        )
