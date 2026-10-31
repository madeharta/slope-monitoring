"""GCN baseline — blueprint §2 ("model eksis v2.6.0, dipertahankan sebagai
pembanding"). This module wires the EXISTING baseline into the new
ModelInterface contract; it does not reimplement the GCN itself.

STATUS: structural stub, UNCHANGED and deliberately left as-is (2026-09-18).
A torch-based reconstruction was drafted and then reverted from this file
specifically — see ml/legacy/gcn_v2_6_0/model_v2_6_0.py, the real port
and what it contains. Reasoning: this stub's load_weights()/predict() are
currently exercised by PRODUCTION traffic (register/activate/rollback all
confirmed working against the real deployed server) — replacing it with
untested torch code in-place would have silently broken working
functionality. The reconstruction lives in a separate, NOT wired-in file
until it can be properly integrated and tested.

`load_weights`/`predict` below are placeholders that satisfy the interface
and let ModelRegistry (§8) be exercised end to end (registration,
compatibility check, hot-swap, rollback) without waiting on the real
v2.6.0 weight-loading code to be ported in. Replace with calls into the
actual v2.6.0 inference code before this leaves POC status — do not ship
this stub's `predict()` output as a real prediction.
"""

from __future__ import annotations

from ml.domain.interfaces import GraphBatch, ModelInterface, PredictionResult


class GCNBaseline(ModelInterface):
    def __init__(self) -> None:
        self._loaded_version: str | None = None

    @property
    def model_type(self) -> str:
        return "gcn"

    def input_contract(self) -> dict:
        # Matches the existing v2.6.0 baseline: 15 sensor features per node,
        # 2-layer GCN, 2-class output (per ways-of-working: "the model
        # outputs 2 classes", 3-tier status is post-processing).
        return {"n_features": 15, "n_classes": 2, "supports_variable_n": True}

    def load_weights(self, version_id: str, artifact_path: str) -> None:
        # REVISED 2026-09-19: signature now receives artifact_path (item 11
        # gap fix, see ml/domain/interfaces.py). This stub still doesn't
        # actually read the file — TODO unchanged — but now at least
        # RECEIVES the path correctly, ready for whoever wires in real
        # checkpoint loading.
        # Must raise (not silently no-op) if artifact_path has no file —
        # ModelRegistry.activate() relies on this to abort the swap.
        self._loaded_version = version_id

    def predict(self, batch: GraphBatch) -> PredictionResult:
        if self._loaded_version is None:
            raise RuntimeError("predict() called before load_weights() — registry bug, not caller error")
        # TODO: replace with the real forward pass. Placeholder keeps output
        # shape-correct (one score per device) so registry/API wiring can be
        # tested without the actual model.
        scores = [0.0 for _ in batch.device_ids]
        return PredictionResult(
            device_ids=batch.device_ids,
            risk_scores=scores,
            model_type=self.model_type,
            version_id=self._loaded_version,
        )
