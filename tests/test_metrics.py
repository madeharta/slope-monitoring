from datetime import UTC, datetime, timedelta

import pytest

from common.metrics import HopTimer, LatencyAccumulator, percentile


def test_percentile_endpoints_and_interpolation():
    data = [float(x) for x in range(1, 101)]  # 1..100, sorted
    assert percentile(data, 0) == 1.0
    assert percentile(data, 100) == 100.0
    # linear interpolation, p50 of 1..100 lands between 50 and 51
    assert percentile(data, 50) == pytest.approx(50.5)


def test_percentile_single_and_empty():
    assert percentile([42.0], 99) == 42.0
    with pytest.raises(ValueError):
        percentile([], 50)


def test_accumulator_summary_reports_percentiles_not_just_mean():
    acc = LatencyAccumulator()
    for v in [10.0, 20.0, 30.0, 40.0, 1000.0]:  # long tail
        acc.add(v)
    s = acc.summary()
    assert s["count"] == 5
    assert s["min"] == 10.0 and s["max"] == 1000.0
    # the tail pulls the mean far above p50 — exactly why we report both
    assert s["p50"] < s["mean"]
    for key in ("p50", "p95", "p99"):
        assert key in s


def test_empty_accumulator():
    assert LatencyAccumulator().summary() == {"count": 0}


def test_hop_timer_attributes_latency_to_a_segment():
    t0 = datetime(2026, 7, 27, 9, 0, 0, tzinfo=UTC)
    timer = HopTimer()
    timer.stamp("mqtt_ingress", t0)
    timer.stamp("consumer_receipt", t0 + timedelta(milliseconds=250))
    assert timer.latency_ms("mqtt_ingress", "consumer_receipt") == pytest.approx(250.0)


def test_hop_timer_rejects_naive():
    with pytest.raises(ValueError):
        HopTimer().stamp("x", datetime(2026, 7, 27, 9, 0, 0))
