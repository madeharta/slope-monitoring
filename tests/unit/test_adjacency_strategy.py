from __future__ import annotations
import random
from datetime import datetime, timezone
from ml.pipeline.graph_builder.adjacency_strategy import (
    AdjacencyStrategySelector,
    DeviceNode,
    GeographicKNNAdjacency,
    MICBasedAdjacency,
    _histogram_mutual_information,
    compute_mic,
    haversine_matrix,
    inverse_distance_weight,
    row_normalize,
)
_NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)
def test_haversine_matches_known_jakarta_bandung_distance():
    dist = haversine_matrix([(-6.2088, 106.8456), (-6.9175, 107.6191)])
    assert 110_000 < dist[0, 1] < 130_000
def test_haversine_identical_points_zero_distance():
    dist = haversine_matrix([(-6.2, 106.8), (-6.2, 106.8)])
    assert dist[0, 1] == 0.0
def test_idw_identical_points_zero_weight_not_infinity():
    dist = haversine_matrix([(-6.2, 106.8), (-6.2, 106.8), (-6.5, 107.0)])
    w = inverse_distance_weight(dist)
    assert w[0, 1] == 0.0
def test_idw_closer_point_gets_higher_weight():
    coords = [(-6.2, 106.8), (-6.2001, 106.8), (-6.9, 107.6)]
    dist = haversine_matrix(coords)
    w = inverse_distance_weight(dist)
    assert w[0, 1] > w[0, 2]
def test_row_normalize_sums_to_one_or_zero():
    w = inverse_distance_weight(haversine_matrix([(-6.2, 106.8), (-6.2, 106.8), (-6.5, 107.0)]))
    norm = row_normalize(w)
    for row in norm:
        s = row.sum()
        assert s == 0.0 or abs(s - 1.0) < 1e-9
def test_geographic_knn_adjacency_builds_correct_shape():
    devices = [DeviceNode("A", -6.2, 106.8), DeviceNode("B", -6.21, 106.81), DeviceNode("C", -6.9, 107.6)]
    adj = GeographicKNNAdjacency().build(devices, _NOW)
    assert adj.shape == (3, 3)
def test_geographic_knn_single_device_returns_zero_matrix_not_crash():
    adj = GeographicKNNAdjacency().build([DeviceNode("A", -6.2, 106.8)], _NOW)
    assert adj.shape == (1, 1)
    assert adj[0, 0] == 0.0
def test_mi_proxy_self_association_is_high():
    random.seed(42)
    x = [random.gauss(0, 1) for _ in range(200)]
    assert _histogram_mutual_information(x, x) > 0.7
def test_compute_mic_too_few_points_returns_zero():
    small = list(range(8))
    assert compute_mic(small, small) == 0.0
def test_compute_mic_self_correlation_is_near_one():
    random.seed(42)
    x = [random.gauss(0, 1) for _ in range(200)]
    assert compute_mic(x, x) > 0.9
def test_compute_mic_independent_noise_is_low():
    random.seed(1)
    y1 = [random.gauss(0, 1) for _ in range(200)]
    random.seed(2)
    y2 = [random.gauss(0, 1) for _ in range(200)]
    mic_self = compute_mic(y1, y1)
    mic_indep = compute_mic(y1, y2)
    assert mic_indep < mic_self
def test_compute_mic_detects_nonlinear_relationship_pearson_misses():
    import numpy as np
    random.seed(7)
    x = [random.uniform(-1, 1) for _ in range(300)]
    y = [v**2 for v in x]
    pearson = np.corrcoef(x, y)[0, 1]
    mic = compute_mic(x, y)
    assert abs(pearson) < 0.3, "Pearson memang harus dekat nol untuk parabola simetris (properti dikenal, bukan asumsi)"
    assert mic > 0.5, "MIC harus mendeteksi hubungan non-linear kuat ini -- itulah keunggulan MIC dibanding Pearson"
def test_mic_adjacency_missing_history_stays_zero_not_error():
    devices = [DeviceNode("A", -6.2, 106.8), DeviceNode("B", -6.21, 106.81)]
    adj = MICBasedAdjacency(displacement_history={}).build(devices, _NOW)
    assert adj.shape == (2, 2)
    assert (adj == 0).all()
def test_selector_picks_idw_for_three_devices():
    devices = [DeviceNode("A", 0, 0), DeviceNode("B", 1, 1), DeviceNode("C", 2, 2)]
    strategy = AdjacencyStrategySelector().select(devices)
    assert isinstance(strategy, GeographicKNNAdjacency)
def test_selector_picks_mic_for_four_devices():
    devices = [DeviceNode(str(i), i, i) for i in range(4)]
    strategy = AdjacencyStrategySelector().select(devices)
    assert isinstance(strategy, MICBasedAdjacency)
