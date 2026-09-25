from __future__ import annotations
from pathlib import Path
from ml.domain.interfaces import GraphBatch, ModelInterface, PredictionResult
FEATURE_COLUMNS = (
    "roll", "pitch", "yaw",
    "delta_roll", "delta_pitch", "delta_yaw",
    "gps_dx", "gps_dy", "gps_dz", "gps_velocity",
    "rainfall_rate", "rainfall_24h", "rainfall_72h", "temperature", "humidity",
)
HIDDEN_DIM = 32
NUM_CLASSES = 2
DROPOUT_RATE = 0.3
RISK_THRESHOLD_WARNING = 0.4
RISK_THRESHOLD_DANGER = 0.7
_CHECKPOINT_PATH = Path(__file__).parent / "checkpoint_v2.6.0.pt"
def _score_to_status(score: float) -> str:
    if score >= RISK_THRESHOLD_DANGER:
        return "DANGER"
    if score >= RISK_THRESHOLD_WARNING:
        return "WARNING"
    return "SAFE"
class GCNv260(ModelInterface):
    def __init__(self) -> None:
        self._torch_model = None
        self._feature_mean = None
        self._feature_std = None
        self._loaded_version: str | None = None
    @property
    def model_type(self) -> str:
        return "gcn_v2_6_0"
    def input_contract(self) -> dict:
        return {
            "n_features": len(FEATURE_COLUMNS),
            "n_classes": NUM_CLASSES,
            "supports_variable_n": True,
            "feature_names": list(FEATURE_COLUMNS),
        }
    def _build_layers(self, input_dim: int, hidden_dim: int):
        import torch.nn as nn
        import torch.nn.functional as F
        from torch_geometric.nn import GCNConv
        class _BaselineGCN(nn.Module):
            def __init__(self):
                super().__init__()
                self.conv1 = GCNConv(input_dim, hidden_dim)
                self.conv2 = GCNConv(hidden_dim, NUM_CLASSES)
                self.dropout = DROPOUT_RATE
            def forward(self, x, edge_index):
                h = self.conv1(x, edge_index)
                h = F.relu(h)
                h = F.dropout(h, p=self.dropout, training=self.training)
                return self.conv2(h, edge_index)
        return _BaselineGCN()
    def load_weights(self, version_id: str, artifact_path: str) -> None:
        import torch
        path = Path(artifact_path) if artifact_path else _CHECKPOINT_PATH
        if not path.exists():
            raise FileNotFoundError(f"checkpoint not found at {path}")
        checkpoint = torch.load(path, weights_only=False)
        self._torch_model = self._build_layers(
            input_dim=checkpoint["input_dim"], hidden_dim=checkpoint["hidden_dim"]
        )
        self._torch_model.load_state_dict(checkpoint["model_state_dict"])
        self._torch_model.eval()
        self._feature_mean = checkpoint["feature_mean"]
        self._feature_std = checkpoint["feature_std"]
        self._loaded_version = checkpoint.get("model_version", version_id)
    def predict(self, batch: GraphBatch) -> PredictionResult:
        if self._torch_model is None:
            raise RuntimeError("predict() called before load_weights()")
        import torch
        raw = torch.tensor(batch.node_features, dtype=torch.float32)
        x = (raw - torch.tensor(self._feature_mean, dtype=torch.float32)) / torch.tensor(
            self._feature_std, dtype=torch.float32
        )
        adjacency = torch.tensor(batch.adjacency, dtype=torch.float32)
        edge_index = adjacency.nonzero(as_tuple=False).t().contiguous()
        with torch.no_grad():
            logits = self._torch_model(x, edge_index)
            risk_scores = torch.softmax(logits, dim=1)[:, 1].tolist()
        return PredictionResult(
            device_ids=batch.device_ids, risk_scores=risk_scores,
            model_type=self.model_type, version_id=self._loaded_version,
        )
    def status_labels(self, risk_scores: list[float]) -> list[str]:
        return [_score_to_status(s) for s in risk_scores]
