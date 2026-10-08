from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
@dataclass(frozen=True)
class EventWindow:
    event_id: str
    start: datetime
    end: datetime
class PurgedGroupTimeSeriesSplit:
    def __init__(self, n_splits: int, embargo: timedelta) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        self.n_splits = n_splits
        self.embargo = embargo
    def split(self, events: list[EventWindow]) -> list[tuple[list[str], list[str]]]:
        ordered = sorted(events, key=lambda e: e.start)
        n = len(ordered)
        if n < self.n_splits + 1:
            raise ValueError(f"need at least {self.n_splits + 1} events for {self.n_splits} splits, got {n}")
        fold_size = n // (self.n_splits + 1)
        folds: list[tuple[list[str], list[str]]] = []
        for k in range(1, self.n_splits + 1):
            split_point = fold_size * k
            train_candidates = ordered[:split_point]
            test_candidates = ordered[split_point : split_point + fold_size]
            if not test_candidates:
                continue
            test_start = test_candidates[0].start
            purge_before = test_start - self.embargo
            purged_train = [e for e in train_candidates if e.end <= purge_before]
            folds.append(
                ([e.event_id for e in purged_train], [e.event_id for e in test_candidates])
            )
        return folds
