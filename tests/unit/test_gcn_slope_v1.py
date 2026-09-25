from __future__ import annotations
import torch
from ml.domain.interfaces import GraphBatch
from ml.models.gcn_slope_v1.model import (
    N_FEATURES,
    GCNSlopeV1,
    add_self_loops_and_normalize,
)
from ml.pipeline.feature_engineering.node_feature_builder import FEATURE_NAMES
def test_n_features_matches_node_feature_builder():
    assert N_FEATURES == len(FEATURE_NAMES)
def test_isolated_device_propagates_as_pure_identity():
    adj = torch.zeros((3, 3))
    norm = add_self_loops_and_normalize(adj)
    assert torch.allclose(norm, torch.eye(3))
def test_normalized_rows_sum_to_one():
    adj = torch.tensor([[0, 0.5, 0.3], [0.5, 0, 0.2], [0.3, 0.2, 0]])
    norm = add_self_loops_and_normalize(adj)
    assert torch.allclose(norm.sum(dim=1), torch.ones(3))
def test_forward_pass_shape_and_no_nan():
    model = GCNSlopeV1()
    model.initialize_random_weights(seed=42)
    adj = [[0, 0.5, 0.3], [0.5, 0, 0.2], [0.3, 0.2, 0]]
    batch = GraphBatch(
        device_ids=["A", "B", "C"],
        node_features=[[float(i)] * N_FEATURES for i in range(3)],
        adjacency=adj,
        window_length=1,
    )
    result = model.predict(batch)
    assert len(result.risk_scores) == 3
    assert all(0.0 <= s <= 1.0 for s in result.risk_scores)
    assert not any(s != s for s in result.risk_scores)
def test_same_seed_gives_identical_predictions():
    adj = torch.eye(2).tolist()
    batch = GraphBatch(device_ids=["A", "B"], node_features=[[0.1] * N_FEATURES] * 2, adjacency=adj, window_length=1)
    m1 = GCNSlopeV1()
    m1.initialize_random_weights(seed=7)
    m2 = GCNSlopeV1()
    m2.initialize_random_weights(seed=7)
    assert m1.predict(batch).risk_scores == m2.predict(batch).risk_scores
def test_scales_to_different_n_without_code_change():
    model = GCNSlopeV1()
    model.initialize_random_weights(seed=1)
    for n in (2, 5, 8):
        batch = GraphBatch(
            device_ids=[f"D{i}" for i in range(n)],
            node_features=[[0.1 * i] * N_FEATURES for i in range(n)],
            adjacency=torch.eye(n).tolist(),
            window_length=1,
        )
        result = model.predict(batch)
        assert len(result.risk_scores) == n
def test_wrong_feature_count_raises_value_error():
    model = GCNSlopeV1()
    model.initialize_random_weights(seed=1)
    bad_batch = GraphBatch(device_ids=["A"], node_features=[[1.0, 2.0]], adjacency=[[0.0]], window_length=1)
    try:
        model.predict(bad_batch)
        assert False, "harusnya raise ValueError"
    except ValueError:
        pass
def test_predict_before_load_weights_raises_runtime_error():
    model = GCNSlopeV1()
    batch = GraphBatch(device_ids=["A"], node_features=[[0.0] * N_FEATURES], adjacency=[[0.0]], window_length=1)
    try:
        model.predict(batch)
        assert False, "harusnya raise RuntimeError"
    except RuntimeError:
        pass
def test_load_weights_raises_filenotfound_for_missing_checkpoint():
    model = GCNSlopeV1()
    try:
        model.load_weights("v1", "/tmp/does-not-exist-slope-monitoring-test.pt")
        assert False, "harusnya raise FileNotFoundError"
    except FileNotFoundError:
        pass
def test_input_contract_matches_new_feature_schema():
    model = GCNSlopeV1()
    contract = model.input_contract()
    assert contract["n_features"] == N_FEATURES
    assert contract["n_features"] != 15
def test_checkpoint_save_and_load_roundtrip(tmp_path):
    model = GCNSlopeV1()
    model.initialize_random_weights(seed=99)
    checkpoint_path = tmp_path / "test_checkpoint.pt"
    torch.save(model.state_dict(), checkpoint_path)
    model2 = GCNSlopeV1()
    model2.load_weights("v1-roundtrip", str(checkpoint_path))
    batch = GraphBatch(
        device_ids=["A"], node_features=[[0.5] * N_FEATURES], adjacency=[[0.0]], window_length=1,
    )
    r1 = model.predict(batch)
    r2 = model2.predict(batch)
    assert r1.risk_scores == r2.risk_scores
