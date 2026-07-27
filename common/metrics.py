"""Latency math shared by the load generator, consumers, and bench harness.

Percentiles first (p50/p95/p99), never mean-only — for an early-warning
system the tail matters more than the average (context.md §8). Mean is
reported too, but always alongside the percentiles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime


def percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile. `q` in [0, 100]. Input must be sorted."""
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty sequence")
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in [0, 100]")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (q / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


@dataclass
class LatencyAccumulator:
    """Collect latency samples (ms) and summarize with percentiles."""

    samples_ms: list[float] = field(default_factory=list)

    def add(self, latency_ms: float) -> None:
        self.samples_ms.append(latency_ms)

    def __len__(self) -> int:
        return len(self.samples_ms)

    def summary(self) -> dict[str, float | int]:
        if not self.samples_ms:
            return {"count": 0}
        s = sorted(self.samples_ms)
        return {
            "count": len(s),
            "min": s[0],
            "p50": percentile(s, 50),
            "p95": percentile(s, 95),
            "p99": percentile(s, 99),
            "max": s[-1],
            "mean": sum(s) / len(s),
        }


@dataclass
class HopTimer:
    """Records named per-hop timestamps so latency can be attributed to a
    specific segment (MQTT ingress, bridge egress, Kafka ingress, consumer
    receipt) rather than only measured end-to-end (context.md §8)."""

    stamps: dict[str, datetime] = field(default_factory=dict)

    def stamp(self, hop: str, when: datetime) -> None:
        if when.tzinfo is None:
            raise ValueError("hop timestamps must be timezone-aware")
        self.stamps[hop] = when

    def latency_ms(self, start_hop: str, end_hop: str) -> float:
        a, b = self.stamps[start_hop], self.stamps[end_hop]
        return (b - a).total_seconds() * 1000.0
