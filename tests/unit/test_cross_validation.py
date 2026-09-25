from datetime import datetime, timedelta
import pytest
from ml.evaluation.cross_validation import EventWindow, PurgedGroupTimeSeriesSplit
_T0 = datetime(2026, 1, 1)
def _events(n: int, spacing_hours: int = 2) -> list[EventWindow]:
    return [
        EventWindow(f"ev{i}", _T0 + timedelta(hours=i * spacing_hours), _T0 + timedelta(hours=i * spacing_hours + 1))
        for i in range(n)
    ]
def test_splits_are_time_ordered_not_shuffled():
    events = _events(12)
    folds = PurgedGroupTimeSeriesSplit(n_splits=3, embargo=timedelta(hours=1)).split(events)
    by_id = {e.event_id: e for e in events}
    for train_ids, test_ids in folds:
        test_min_start = min(by_id[t].start for t in test_ids)
        for tid in train_ids:
            assert by_id[tid].start < test_min_start
def test_no_event_appears_in_both_train_and_test():
    events = _events(12)
    folds = PurgedGroupTimeSeriesSplit(n_splits=3, embargo=timedelta(hours=1)).split(events)
    for train_ids, test_ids in folds:
        assert not (set(train_ids) & set(test_ids))
def test_purging_actively_removes_events_inside_embargo_zone():
    events = [
        EventWindow("ev0", _T0, _T0 + timedelta(hours=1)),
        EventWindow("ev1", _T0 + timedelta(hours=2), _T0 + timedelta(hours=3)),
        EventWindow("ev2", _T0 + timedelta(hours=4), _T0 + timedelta(hours=5)),
        EventWindow("ev3_straddles_embargo", _T0 + timedelta(hours=5, minutes=30), _T0 + timedelta(hours=5, minutes=45)),
        EventWindow("ev4", _T0 + timedelta(hours=6), _T0 + timedelta(hours=7)),
        EventWindow("ev5", _T0 + timedelta(hours=8), _T0 + timedelta(hours=9)),
    ]
    folds = PurgedGroupTimeSeriesSplit(n_splits=2, embargo=timedelta(hours=1)).split(events)
    train1, _test1 = folds[1]
    assert "ev3_straddles_embargo" not in train1
    assert "ev2" in train1
def test_rejects_too_few_events():
    with pytest.raises(ValueError):
        PurgedGroupTimeSeriesSplit(n_splits=5, embargo=timedelta(hours=1)).split(_events(3))
def test_rejects_n_splits_below_two():
    with pytest.raises(ValueError):
        PurgedGroupTimeSeriesSplit(n_splits=1, embargo=timedelta(hours=1))
