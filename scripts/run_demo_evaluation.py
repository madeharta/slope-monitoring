from __future__ import annotations
from datetime import datetime, timedelta, timezone
from ml.evaluation.cross_validation import EventWindow
from ml.evaluation.training_pipeline import NodeState, run_purged_evaluation
from ml.models.gcn_slope_v1.model import GCNSlopeV1
from ml.pipeline.feature_engineering.displacement import DisplacementMM
_BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
def _synthetic_event(event_id: str, day_offset: int, risk_total_mm: float, n_normal_devices: int = 2) -> tuple[EventWindow, list[NodeState]]:
    start = _BASE_TIME + timedelta(days=day_offset)
    end = start + timedelta(minutes=10)
    epoch_s = start.timestamp()
    states = []
    for i in range(n_normal_devices):
        states.append(NodeState(
            device_id=f"SIM-NORMAL-{i}", lat=-6.867 + i * 0.001, lon=107.578 + i * 0.001,
            displacement=DisplacementMM(de_mm=1.0, dn_mm=1.0, du_mm=0.2, total_mm=1.5),
            epoch_s=epoch_s, h_acc_m=0.3, label=0,
        ))
    states.append(NodeState(
        device_id="SIM-RISK-0", lat=-6.870, lon=107.580,
        displacement=DisplacementMM(de_mm=risk_total_mm * 0.7, dn_mm=risk_total_mm * 0.6, du_mm=risk_total_mm * 0.2, total_mm=risk_total_mm),
        epoch_s=epoch_s, h_acc_m=0.5, label=1,
    ))
    return EventWindow(event_id=event_id, start=start, end=end), states
def main() -> None:
    events = []
    node_states_by_event = {}
    for i in range(8):
        event, states = _synthetic_event(f"sim-event-{i}", day_offset=i, risk_total_mm=20.0 + i * 5)
        events.append(event)
        node_states_by_event[event.event_id] = states
    print(f"Menjalankan Purged CV (3 fold) atas {len(events)} event sintetis...")
    results = run_purged_evaluation(
        events=events, node_states_by_event=node_states_by_event,
        model_factory=GCNSlopeV1, n_splits=3, embargo=timedelta(hours=12), epochs=20,
    )
    for i, r in enumerate(results):
        print(f"Fold {i + 1}: {r}")
    print("\nSelesai. INGAT: ini data SINTETIS, akurasi di atas TIDAK berarti model siap "
          "pakai — cuma bukti pipa split->fitur->adjacency->training->evaluasi tersambung benar.")
if __name__ == "__main__":
    main()
