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
    "gcn_slope_v1": GCNSlopeV1,
}
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
