from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from ml.domain.interfaces import GraphBatch
from ml.evaluation.cross_validation import EventWindow, PurgedGroupTimeSeriesSplit
from ml.pipeline.feature_engineering.displacement import DisplacementMM
from ml.pipeline.feature_engineering.node_feature_builder import build_node_features
from ml.pipeline.feature_engineering.tilt import TiltDeg
from ml.pipeline.feature_engineering.vibration import VibrationMetrics
from ml.pipeline.graph_builder.adjacency_strategy import AdjacencyStrategySelector, DeviceNode
@dataclass(frozen=True)
class NodeState:
    device_id: str
    lat: float
    lon: float
    displacement: DisplacementMM
    epoch_s: float
    h_acc_m: float
    previous_displacement: DisplacementMM | None = None
    previous_epoch_s: float | None = None
    vibration: VibrationMetrics | None = None
    tilt: TiltDeg | None = None
    label: int = 0
def assemble_graph_batch(node_states: list[NodeState], timestep: datetime) -> tuple[GraphBatch, list[int]]:
    if not node_states:
        raise ValueError("assemble_graph_batch requires at least one NodeState")
    device_nodes = [DeviceNode(device_id=ns.device_id, lat=ns.lat, lon=ns.lon) for ns in node_states]
    strategy = AdjacencyStrategySelector().select(device_nodes)
    adjacency = strategy.build(device_nodes, timestep)
    node_features = []
    labels = []
    for ns in node_states:
        vec = build_node_features(
            device_id=ns.device_id, displacement=ns.displacement, current_epoch_s=ns.epoch_s, h_acc_m=ns.h_acc_m,
            previous_displacement=ns.previous_displacement, previous_epoch_s=ns.previous_epoch_s,
            vibration=ns.vibration, tilt=ns.tilt,
        )
        node_features.append(list(vec.to_tensor_row()))
        labels.append(ns.label)
    batch = GraphBatch(
        device_ids=[ns.device_id for ns in node_states],
        node_features=node_features,
        adjacency=adjacency.tolist(),
        window_length=1,
    )
    return batch, labels
def train_one_fold(model, train_batches: list[tuple[GraphBatch, list[int]]], test_batches: list[tuple[GraphBatch, list[int]]], epochs: int = 10, lr: float = 0.01) -> dict:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.BCELoss()
    model.train()
    for _epoch in range(epochs):
        for batch, labels in train_batches:
            optimizer.zero_grad()
            x = torch.tensor(batch.node_features, dtype=torch.float32)
            adjacency = torch.tensor(batch.adjacency, dtype=torch.float32)
            h1 = F.relu(model.conv1(x, adjacency))
            h2 = torch.sigmoid(model.conv2(h1, adjacency))
            pred = h2[:, 1]
            target = torch.tensor(labels, dtype=torch.float32)
            loss = loss_fn(pred, target)
            loss.backward()
            optimizer.step()
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for batch, labels in test_batches:
            result = model.predict(batch)
            for score, true_label in zip(result.risk_scores, labels):
                predicted = 1 if score > 0.5 else 0
                correct += int(predicted == true_label)
                total += 1
    return {"accuracy": correct / total if total > 0 else 0.0, "n_test_nodes": total}
def build_fold_batches(
    event_ids: list[str], node_states_by_event: dict[str, list[NodeState]], event_timestamps: dict[str, datetime],
) -> list[tuple[GraphBatch, list[int]]]:
    batches = []
    for event_id in event_ids:
        if event_id not in node_states_by_event:
            continue
        batch, labels = assemble_graph_batch(node_states_by_event[event_id], event_timestamps[event_id])
        batches.append((batch, labels))
    return batches
def run_purged_evaluation(
    events: list[EventWindow],
    node_states_by_event: dict[str, list[NodeState]],
    model_factory,
    n_splits: int = 3,
    embargo: timedelta = timedelta(hours=1),
    epochs: int = 10,
) -> list[dict]:
    event_timestamps = {e.event_id: e.start for e in events}
    splitter = PurgedGroupTimeSeriesSplit(n_splits=n_splits, embargo=embargo)
    folds = splitter.split(events)
    results = []
    for train_ids, test_ids in folds:
        train_batches = build_fold_batches(train_ids, node_states_by_event, event_timestamps)
        test_batches = build_fold_batches(test_ids, node_states_by_event, event_timestamps)
        if not train_batches or not test_batches:
            results.append({"accuracy": None, "n_test_nodes": 0, "skipped": "train atau test fold kosong setelah purging"})
            continue
        model = model_factory()
        model.initialize_random_weights()
        metrics = train_one_fold(model, train_batches, test_batches, epochs=epochs)
        results.append(metrics)
    return results
