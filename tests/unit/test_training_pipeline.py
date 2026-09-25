from __future__ import annotations
from datetime import datetime, timezone
from ml.evaluation.training_pipeline import NodeState, assemble_graph_batch, build_fold_batches
from ml.pipeline.feature_engineering.displacement import DisplacementMM
from ml.pipeline.feature_engineering.node_feature_builder import FEATURE_NAMES
_NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)
def _state(device_id: str, total_mm: float, label: int = 0) -> NodeState:
    return NodeState(
        device_id=device_id, lat=-6.867, lon=107.578,
        displacement=DisplacementMM(de_mm=total_mm * 0.6, dn_mm=total_mm * 0.6, du_mm=total_mm * 0.1, total_mm=total_mm),
        epoch_s=1000.0, h_acc_m=0.4, label=label,
    )
def test_assemble_graph_batch_shapes_and_labels():
    states = [_state("ROVER-01", 5.4, label=0), _state("lsm-unconfigured", 1.5, label=0), _state("ROVER-99-SIM", 59.2, label=1)]
    batch, labels = assemble_graph_batch(states, _NOW)
    assert batch.device_ids == ["ROVER-01", "lsm-unconfigured", "ROVER-99-SIM"]
    assert len(batch.node_features) == 3
    assert all(len(row) == len(FEATURE_NAMES) for row in batch.node_features)
    assert len(batch.adjacency) == 3 and len(batch.adjacency[0]) == 3
    assert labels == [0, 0, 1]
def test_assemble_graph_batch_feature_values_match_input():
    states = [_state("ROVER-01", 5.4)]
    batch, _labels = assemble_graph_batch(states, _NOW)
    total_mm_idx = FEATURE_NAMES.index("total_mm")
    assert abs(batch.node_features[0][total_mm_idx] - 5.4) < 1e-9
def test_assemble_graph_batch_empty_raises():
    try:
        assemble_graph_batch([], _NOW)
        assert False, "harusnya raise ValueError"
    except ValueError:
        pass
def test_build_fold_batches_skips_events_without_node_states():
    node_states_by_event = {"ev1": [_state("ROVER-01", 1.7)]}
    event_timestamps = {"ev1": _NOW, "ev2": _NOW}
    batches = build_fold_batches(["ev1", "ev2"], node_states_by_event, event_timestamps)
    assert len(batches) == 1
    batch, labels = batches[0]
    assert batch.device_ids == ["ROVER-01"]
    assert labels == [0]
def test_build_fold_batches_empty_event_list_returns_empty():
    assert build_fold_batches([], {}, {}) == []
