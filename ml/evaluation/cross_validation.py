"""Purged Group TimeSeries Split — blueprint §7. Was design-only (docstring
in blueprint, no code) until this file — see METODOLOGI_END_TO_END_TERKOREKSI.md
Tahap 6, which flagged this gap while correcting the paper narrative.

Methodology origin: López de Prado, M. (2018). *Advances in Financial
Machine Learning*. Wiley, Chapter 7 ("Cross-Validation in Finance") —
introduces purging + embargo for time-ordered data with overlapping
labels. That book's domain is finance; the leakage MECHANISM (features
computed over overlapping windows leaking across a train/test boundary)
is domain-agnostic, which is why it transfers to this system's event
windows (blast/movement episodes) — but "group by event" itself is this
project's own adaptation of the general idea, not taken verbatim from the
book (the book groups by overlapping label horizon, not physical events).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class EventWindow:
    """One group — one physical event (a blast, or a contiguous movement
    episode), not one sample. `start`/`end` bound every sample belonging
    to this event, INCLUDING any lookback window feature engineering
    consumed — callers must pass the full feature-computation span here,
    not just the raw event timestamps, or purging will under-purge."""

    event_id: str
    start: datetime
    end: datetime


class PurgedGroupTimeSeriesSplit:
    """Time-ordered, event-grouped cross-validation with purge + embargo.

    Unlike sklearn's GroupKFold (which shuffles group ASSIGNMENT to folds
    but not fold ORDER), this split is time-ordered: fold k's events are
    always chronologically later than fold k-1's. This is what makes it
    valid for sequential deformation/vibration data, where a model must
    never be evaluated on data that precedes what it trained on.
    """

    def __init__(self, n_splits: int, embargo: timedelta) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        self.n_splits = n_splits
        self.embargo = embargo

    def split(self, events: list[EventWindow]) -> list[tuple[list[str], list[str]]]:
        """Returns a list of (train_event_ids, test_event_ids) tuples, one
        per fold. Events are sorted by start time first — caller order is
        NOT assumed to already be chronological."""
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

            # Purge: drop any "train" event whose window extends into the
            # embargo zone right before the test fold starts — this is
            # where overlapping-feature leakage would otherwise sneak in.
            purged_train = [e for e in train_candidates if e.end <= purge_before]

            folds.append(
                ([e.event_id for e in purged_train], [e.event_id for e in test_candidates])
            )

        return folds
