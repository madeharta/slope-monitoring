from __future__ import annotations
from ml.pipeline.feature_engineering.displacement import DisplacementMM
from ml.pipeline.feature_engineering.node_feature_builder import (
    FEATURE_NAMES,
    build_node_features,
    compute_velocity_mm_day,
)
from ml.pipeline.feature_engineering.tilt import TiltDeg
from ml.pipeline.feature_engineering.vibration import VibrationMetrics
def test_without_history_or_vibration_or_tilt_defaults_to_zero_not_error():
    d = DisplacementMM(de_mm=5.0, dn_mm=3.0, du_mm=1.0, total_mm=5.9)
    f = build_node_features("ROVER-01", d, current_epoch_s=1000.0, h_acc_m=0.02)
    assert f.velocity_mm_day == 0.0
    assert f.ppa_g == 0.0 and f.ppv_mm_s == 0.0
    assert f.tilt_x_deg == 0.0 and f.tilt_y_deg == 0.0
    assert f.h_acc_m == 0.02
def test_velocity_computed_correctly_across_one_day():
    d0 = DisplacementMM(de_mm=0.0, dn_mm=0.0, du_mm=0.0, total_mm=0.0)
    d1 = DisplacementMM(de_mm=10.0, dn_mm=0.0, du_mm=0.0, total_mm=10.0)
    f = build_node_features(
        "ROVER-01", d1, current_epoch_s=86400.0, h_acc_m=0.02,
        previous_displacement=d0, previous_epoch_s=0.0,
    )
    assert abs(f.velocity_mm_day - 10.0) < 1e-9
def test_full_vector_has_all_ten_features_in_declared_order():
    d = DisplacementMM(de_mm=5.0, dn_mm=3.0, du_mm=1.0, total_mm=5.9)
    vib = VibrationMetrics(ppa_g=0.5, ppv_mm_s=12.0, sample_count=1000)
    tilt = TiltDeg(tilt_x_deg=1.2, tilt_y_deg=-0.5, sample_count=50)
    f = build_node_features("ROVER-01", d, current_epoch_s=1000.0, h_acc_m=0.02, vibration=vib, tilt=tilt)
    row = f.to_tensor_row()
    assert len(row) == len(FEATURE_NAMES) == 10
    assert row[FEATURE_NAMES.index("ppa_g")] == 0.5
    assert row[FEATURE_NAMES.index("tilt_x_deg")] == 1.2
    assert row[FEATURE_NAMES.index("total_mm")] == 5.9
def test_non_positive_dt_returns_zero_velocity_not_crash():
    d0 = DisplacementMM(de_mm=0.0, dn_mm=0.0, du_mm=0.0, total_mm=0.0)
    d1 = DisplacementMM(de_mm=10.0, dn_mm=0.0, du_mm=0.0, total_mm=10.0)
    f = build_node_features(
        "ROVER-01", d1, current_epoch_s=0.0, h_acc_m=0.02,
        previous_displacement=d0, previous_epoch_s=100.0,
    )
    assert f.velocity_mm_day == 0.0
def test_compute_velocity_mm_day_directly_none_previous():
    assert compute_velocity_mm_day(10.0, None, 100.0, None) == 0.0
def test_compute_velocity_mm_day_directly_known_value():
    v = compute_velocity_mm_day(5.0, 0.0, 43200.0, 0.0)
    assert abs(v - 10.0) < 1e-9
