from __future__ import annotations
from dataclasses import dataclass
from ml.pipeline.feature_engineering.displacement import DisplacementMM
from ml.pipeline.feature_engineering.tilt import TiltDeg
from ml.pipeline.feature_engineering.vibration import VibrationMetrics
FEATURE_NAMES: tuple[str, ...] = (
    "de_mm", "dn_mm", "du_mm", "total_mm",
    "velocity_mm_day",
    "ppa_g", "ppv_mm_s",
    "tilt_x_deg", "tilt_y_deg",
    "h_acc_m",
)
@dataclass(frozen=True)
class NodeFeatureVector:
    device_id: str
    de_mm: float
    dn_mm: float
    du_mm: float
    total_mm: float
    velocity_mm_day: float
    ppa_g: float
    ppv_mm_s: float
    tilt_x_deg: float
    tilt_y_deg: float
    h_acc_m: float
    def to_tensor_row(self) -> tuple[float, ...]:
        return (
            self.de_mm, self.dn_mm, self.du_mm, self.total_mm,
            self.velocity_mm_day,
            self.ppa_g, self.ppv_mm_s,
            self.tilt_x_deg, self.tilt_y_deg,
            self.h_acc_m,
        )
def compute_velocity_mm_day(
    current_total_mm: float, previous_total_mm: float | None,
    current_epoch_s: float, previous_epoch_s: float | None,
) -> float:
    if previous_total_mm is None or previous_epoch_s is None:
        return 0.0
    dt_days = (current_epoch_s - previous_epoch_s) / 86400.0
    if dt_days <= 0:
        return 0.0
    return (current_total_mm - previous_total_mm) / dt_days
def build_node_features(
    device_id: str,
    displacement: DisplacementMM,
    current_epoch_s: float,
    h_acc_m: float,
    previous_displacement: DisplacementMM | None = None,
    previous_epoch_s: float | None = None,
    vibration: VibrationMetrics | None = None,
    tilt: TiltDeg | None = None,
) -> NodeFeatureVector:
    velocity = compute_velocity_mm_day(
        displacement.total_mm,
        previous_displacement.total_mm if previous_displacement else None,
        current_epoch_s, previous_epoch_s,
    )
    return NodeFeatureVector(
        device_id=device_id,
        de_mm=displacement.de_mm, dn_mm=displacement.dn_mm,
        du_mm=displacement.du_mm, total_mm=displacement.total_mm,
        velocity_mm_day=velocity,
        ppa_g=vibration.ppa_g if vibration else 0.0,
        ppv_mm_s=vibration.ppv_mm_s if vibration else 0.0,
        tilt_x_deg=tilt.tilt_x_deg if tilt else 0.0,
        tilt_y_deg=tilt.tilt_y_deg if tilt else 0.0,
        h_acc_m=h_acc_m,
    )
