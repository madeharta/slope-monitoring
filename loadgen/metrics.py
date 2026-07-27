"""Load-generator metrics. The pure latency math lives in `common.metrics`
so producers and consumers share one implementation; re-exported here for
the placement called out in the loadgen design."""

from common.metrics import HopTimer, LatencyAccumulator, percentile

__all__ = ["HopTimer", "LatencyAccumulator", "percentile"]
