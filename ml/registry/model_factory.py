"""Factory Pattern — blueprint §3.2. Router/service code never does
`if model_type == "gcn": ...`; it calls ModelFactory.create(type) only.

Only 'gcn' is wired to a real (stub) implementation today. 'temporal',
'st_gcn', 'st_gat' are registered as NotImplemented placeholders so the
factory's error message is honest about what exists, while the *shape* of
the registry (dict keyed by model_type, single create() entry point) is
already final per the approved blueprint.
"""

from __future__ import annotations

from ml.domain.interfaces import ModelInterface
from ml.models.gcn_baseline.model import GCNBaseline
from ml.models.gcn_slope_v1.model import GCNSlopeV1


class UnknownModelTypeError(ValueError):
    def __init__(self, model_type: str, available: list[str]) -> None:
        self.model_type = model_type
        self.available = available
        super().__init__(f"unknown model_type '{model_type}'; available: {available}")


class ModelNotImplementedError(NotImplementedError):
    def __init__(self, model_type: str) -> None:
        self.model_type = model_type
        super().__init__(
            f"model_type '{model_type}' is registered but not yet implemented "
            f"(architecture pending — see blueprint §3.2 roadmap)"
        )


_IMPLEMENTED: dict[str, type[ModelInterface]] = {
    "gcn": GCNBaseline,
    # BARU (2026-09-21) — arsitektur GCN dengan skema fitur SENSOR ASLI
    # (10 fitur, node_feature_builder.py), BUKAN "gcn" di atas (stub
    # placeholder 15-fitur v2.6.0 lama yang dipakai traffic produksi —
    # TIDAK disentuh, lihat model.py untuk alasan). Arsitektur+forward
    # pass BEKERJA dan TERUJI (test_gcn_slope_v1.py), TAPI belum ada
    # bobot terlatih sama sekali (load_weights() akan raise
    # FileNotFoundError sampai ada checkpoint sungguhan — itu perilaku
    # BENAR, bukan bug, karena belum ada data cukup untuk training).
    "gcn_slope_v1": GCNSlopeV1,
}

# Registered-but-not-implemented — kept here (not silently absent) so
# `ModelFactory.available_types()` reflects the full roadmap, and requesting
# one gives a clear "not implemented" error instead of "unknown type".
_PLANNED: set[str] = {"temporal", "st_gcn", "st_gat"}


class ModelFactory:
    @staticmethod
    def available_types() -> list[str]:
        return sorted(_IMPLEMENTED) + sorted(_PLANNED)

    @staticmethod
    def create(model_type: str) -> ModelInterface:
        if model_type in _IMPLEMENTED:
            return _IMPLEMENTED[model_type]()
        if model_type in _PLANNED:
            raise ModelNotImplementedError(model_type)
        raise UnknownModelTypeError(model_type, ModelFactory.available_types())
