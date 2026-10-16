"""GCN v2.6.0 — REAL PORT (2026-09-18), not a reconstruction. Source: user-
supplied `csl_gnn/model.py`, `csl_gnn/dataset.py`, `csl_gnn/train.py`,
`api/inference.py`, real trained checkpoint `checkpoint_v2.6.0.pt`
(copied byte-for-byte from `artifacts/model.pt`).

=============================================================================
CRITICAL FINDING — READ BEFORE USING THIS MODEL
=============================================================================
v2.6.0's 15-feature input schema is:

    roll, pitch, yaw, delta_roll, delta_pitch, delta_yaw,          (IMU orientation)
    gps_dx, gps_dy, gps_dz, gps_velocity,                          (GNSS movement)
    rainfall_rate, rainfall_24h, rainfall_72h, temperature, humidity  (weather)

This system's ACTUAL sensor pipeline (blueprint §4, API Spec LoRa/4G) does
NOT produce roll/pitch/yaw (no gyroscope/magnetometer — the hardware is
GNSS + ADXL355/MPU9250 ACCELEROMETER only, not a full IMU with orientation
fusion) and does NOT produce rainfall/temperature/humidity (no weather
station in the API Spec at all). Our pipeline produces dE/dN/dU
displacement, PPA/PPV vibration, h_acc_m, gnss_fix_type — a DIFFERENT
15-ish-feature space entirely, not a superset or renaming of v2.6.0's.

This is a genuine schema incompatibility, not a plumbing problem an
adapter can paper over: 9 of v2.6.0's 15 features (6 IMU + 5 weather,
overlapping is not 1:1) simply have no source in our hardware today.
**This model CANNOT run real inference on our production sensor data
as-is.** It can only run on its original dummy/synthetic feature schema
(or real ITB IMU+weather data, IF that is ever collected by different
hardware than what's currently deployed).

What this file DOES provide, faithfully: a working port of the real
architecture + real trained weights, wired to `ModelInterface`, runnable
standalone against v2.6.0's OWN feature schema. Registered under
`model_type = "gcn_v2_6_0"` — deliberately NOT `"gcn"`, so it never
collides with or silently replaces the currently-active production stub
(`ml/models/gcn_baseline/model.py`) or the untested reconstruction
(the speculative reconstruction this superseded was deleted 2026-09-19 —
see PROJECT_AUDIT_LOG.md). NOT added to
`ml/registry/model_factory.py`'s `_IMPLEMENTED` dict — importing this file
has zero effect on the running system until someone deliberately wires it
in, by design (same "don't touch what's working" policy as last time).

Also NEVER EXECUTED in this session — torch/torch_geometric are not
installed in this sandbox. Structural fidelity to the source (class
shapes, forward-pass order, checkpoint keys) was verified by direct
reading of the uploaded source files, not by running this code.
"""

from __future__ import annotations

from pathlib import Path

from ml.domain.interfaces import GraphBatch, ModelInterface, PredictionResult

# Exact order from the real csl_gnn/config.py — do not reorder, the
# checkpoint's learned weights are order-dependent (conv1's input
# dimension is a flat 15-vector, not named columns).
FEATURE_COLUMNS = (
    "roll", "pitch", "yaw",
    "delta_roll", "delta_pitch", "delta_yaw",
    "gps_dx", "gps_dy", "gps_dz", "gps_velocity",
    "rainfall_rate", "rainfall_24h", "rainfall_72h", "temperature", "humidity",
)
HIDDEN_DIM = 32           # csl_gnn/config.py HIDDEN_DIM_DEFAULT
NUM_CLASSES = 2            # csl_gnn/config.py NUM_CLASSES
DROPOUT_RATE = 0.3          # csl_gnn/config.py DROPOUT_RATE_DEFAULT — inert at eval() time, kept for fidelity
RISK_THRESHOLD_WARNING = 0.4  # csl_gnn/config.py — 3-tier status mapping
RISK_THRESHOLD_DANGER = 0.7

_CHECKPOINT_PATH = Path(__file__).parent / "checkpoint_v2.6.0.pt"


def _score_to_status(score: float) -> str:
    """Ported verbatim from api/inference.py::_score_to_status."""
    if score >= RISK_THRESHOLD_DANGER:
        return "DANGER"
    if score >= RISK_THRESHOLD_WARNING:
        return "WARNING"
    return "SAFE"


class GCNv260(ModelInterface):
    def __init__(self) -> None:
        self._torch_model = None
        self._feature_mean = None  # numpy array, shape (15,) — from checkpoint, NOT recomputed
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
            "feature_names": list(FEATURE_COLUMNS),  # extra field vs other models —
            # ModelRegistry.compatibility_check() (§8.2) only reads n_features
            # today, doesn't cross-check names. This is exactly the kind of
            # silent-mismatch risk the schema incompatibility above describes:
            # a caller passing our own 15 (different!) features would pass
            # compatibility_check (same COUNT) and get nonsense predictions.
            # Flagged, not fixed — fixing it means teaching ModelRegistry to
            # compare feature_names too, out of scope for this port.
        }

    def _build_layers(self, input_dim: int, hidden_dim: int):
        """Ported verbatim from csl_gnn/model.py::BaselineGCN."""
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
        """Ported from csl_gnn/train.py::load_checkpoint.

        REVISED 2026-09-19 (item 11 gap fix): now genuinely uses
        `artifact_path` instead of the hardcoded `_CHECKPOINT_PATH` this
        class used before ModelInterface gained the parameter — THAT
        hardcoding was the exact real-world instance of the gap flagged
        when this file was first written ("no model can load a real
        checkpoint from an arbitrary path"). `_CHECKPOINT_PATH` (the
        bundled `checkpoint_v2.6.0.pt` next to this file) is kept as the
        fallback ONLY when `artifact_path` is empty/falsy, so existing
        callers that registered this model with `artifact_path=""` (e.g.
        any earlier manual test) keep working — a real caller should
        always register with a real path pointing at a checkpoint file.
        """
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
        """Ported from api/inference.py::run_inference, with ONE deliberate
        divergence flagged explicitly: the original builds its OWN k-NN
        haversine graph from raw lat/lon (csl_gnn/dataset.py::build_edge_index).
        This port instead uses `batch.adjacency` — the adjacency this
        system's own graph_builder computed (blueprint §6, IDW/MIC) —
        converted to edge_index/edge_weight. This is an integration choice
        (use THIS system's adjacency strategy, not v2.6.0's original one),
        not an oversight — but it means predictions from this port are NOT
        guaranteed numerically identical to the original API's output even
        given identical raw features, since the graph topology feeding the
        GCN differs. GCNConv's forward signature in the original source
        does not take edge_weight at all (see _build_layers above, ported
        verbatim) — so edge_weight computed below is UNUSED; flagged rather
        than silently dropped.
        """
        if self._torch_model is None:
            raise RuntimeError("predict() called before load_weights()")
        import torch

        raw = torch.tensor(batch.node_features, dtype=torch.float32)
        x = (raw - torch.tensor(self._feature_mean, dtype=torch.float32)) / torch.tensor(
            self._feature_std, dtype=torch.float32
        )

        adjacency = torch.tensor(batch.adjacency, dtype=torch.float32)
        edge_index = adjacency.nonzero(as_tuple=False).t().contiguous()
        # edge_weight = adjacency[edge_index[0], edge_index[1]]  # computed, unused — see docstring

        with torch.no_grad():
            logits = self._torch_model(x, edge_index)
            risk_scores = torch.softmax(logits, dim=1)[:, 1].tolist()  # P(class="warning")

        return PredictionResult(
            device_ids=batch.device_ids, risk_scores=risk_scores,
            model_type=self.model_type, version_id=self._loaded_version,
        )

    def status_labels(self, risk_scores: list[float]) -> list[str]:
        """Not part of ModelInterface (3-tier status is post-processing per
        this project's own convention, confirmed in memory notes) — exposed
        as a plain helper so callers CAN reproduce v2.6.0's original
        SAFE/WARNING/DANGER mapping if they want it, without baking it into
        the interface contract every other model must also satisfy."""
        return [_score_to_status(s) for s in risk_scores]
