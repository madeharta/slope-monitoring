#!/usr/bin/env python3
"""MAGRIS · summarize one benchmark run into a single comparable row.

Reads the JMeter .jtl (client-side: throughput + latency) and the docker-stats
CSV (server-side: broker CPU/mem), and prints one line you can paste straight
into the results table in bench/BENCHMARK.md.

Usage:
  python bench/summarize.py --label 500dev \
      --jtl bench/results/jmeter-500.jtl \
      --stats bench/results/stats-500dev.csv

Either file may be omitted (e.g. emqtt-bench runs have no .jtl).

Two things this deliberately does NOT do naively:

1. Connect and Publish samples are kept apart. A connect failure recorded AFTER
   that thread already connected once is an artefact of re-running the connect
   sampler on a later loop iteration, not a broker failure — counting it made
   every scale report ~49.7% errors. Only a connect failure seen BEFORE that
   thread's first success is real. (The .jmx now wraps connect in a Once Only
   controller, so new runs should show none of either; the classification stays
   so that older .jtl files re-summarize correctly.)

2. The first `--warmup` seconds are discarded before computing anything, per the
   project convention — connection ramp-up otherwise contaminates the tail.
   Broker stats are filtered to the same window so client and server numbers
   describe the same slice of time.
"""

from __future__ import annotations

import argparse
import csv
import statistics as st
from pathlib import Path

BROKER = "magris-variant-a-mosquitto-1"

# An idle stretch at least this long inside one .jtl means two runs were
# concatenated (jmeter -l appends to an existing file).
APPEND_GAP_S = 60.0


def pct(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated percentile over an already-sorted list."""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def read_jtl(path: str, warmup_s: float) -> dict | None:
    """JMeter CSV .jtl -> connection counts, publish percentiles, throughput.

    Returns None if the file has no usable rows.

    Streams the file in two passes rather than materialising it. A high-rate run
    can exceed 500 MB / several million rows, and holding that as a list of dicts
    needs gigabytes; two passes over the file cost far less than the memory would.
    """
    src = Path(path)

    # Pass 1 — timestamps only, to find the run boundary.
    stamps: list[int] = []
    with src.open(encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            ts = r.get("timeStamp", "")
            if ts.isdigit():
                stamps.append(int(ts))
    if not stamps:
        return None
    stamps.sort()

    # `jmeter -l file` APPENDS when the file already exists, so re-running a scale
    # silently concatenates two runs into one .jtl (twice the connections, a span
    # covering the idle gap between them). Detect that and keep only the last run.
    appended_s = 0.0
    run_start = stamps[0]
    if len(stamps) > 1:
        gap, at = max((stamps[i + 1] - stamps[i], i) for i in range(len(stamps) - 1))
        if gap / 1000 >= APPEND_GAP_S:
            appended_s = gap / 1000
            run_start = stamps[at + 1]
    del stamps

    t0 = run_start + warmup_s * 1000  # discard the ramp-up window

    conn_ok = conn_real_fail = conn_artifact = 0
    pub_ok: list[int] = []
    pub_fail = 0
    pub_bytes = 0
    pub_first = pub_last = None
    connected: set[str] = set()  # threads that have completed a successful connect

    # Pass 2 — accumulate. Only publish latencies are retained, as plain ints.
    with src.open(encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            ts_raw = r.get("timeStamp", "")
            ts = int(ts_raw) if ts_raw.isdigit() else None
            if ts is not None and ts < run_start:
                continue  # belongs to an earlier appended run

            label = r.get("label") or ""
            success = r.get("success") == "true"

            if "Publish" not in label:
                # Connect / DisConnect. Classified over the WHOLE run, not just the
                # post-warmup window: connects happen during ramp-up by definition.
                if "Connect" not in label:
                    continue
                thread = r.get("threadName") or ""
                if success:
                    conn_ok += 1
                    connected.add(thread)
                elif thread in connected:
                    conn_artifact += 1
                else:
                    conn_real_fail += 1
                continue

            if ts is None or ts < t0:
                continue  # inside warm-up — ignore
            if not success:
                pub_fail += 1
                continue
            elapsed = r.get("elapsed", "")
            if elapsed.lstrip("-").isdigit():
                pub_ok.append(int(elapsed))
            sent = r.get("sentBytes", "")
            if sent.isdigit():
                pub_bytes += int(sent)
            if pub_first is None or ts < pub_first:
                pub_first = ts
            if pub_last is None or ts > pub_last:
                pub_last = ts

    pub_ok.sort()
    span_s = (pub_last - pub_first) / 1000 if pub_first is not None and pub_last else 0
    pub_total = len(pub_ok) + pub_fail

    return {
        "conn_ok": conn_ok,
        "conn_real_fail": conn_real_fail,
        "conn_artifact": conn_artifact,
        "pub_ok": len(pub_ok),
        "pub_fail": pub_fail,
        "err_pct": 100 * pub_fail / pub_total if pub_total else 0.0,
        "thrpt": len(pub_ok) / span_s if span_s else 0.0,
        "mbps": (pub_bytes / span_s / 1_048_576) if span_s else 0.0,
        "window_s": span_s,
        "p50": pct(pub_ok, 50),
        "p95": pct(pub_ok, 95),
        "p99": pct(pub_ok, 99),
        "max": pub_ok[-1] if pub_ok else 0,
        "t0_ms": t0,
        "t1_ms": pub_last or 0,
        "appended_s": appended_s,
    }


def _mib(raw: str) -> float | None:
    """'31.2MiB / 19.5GiB' -> 31.2 (MiB). None if unparseable."""
    v = raw.split("/")[0].strip()
    mult = {"KiB": 1 / 1024, "MiB": 1.0, "GiB": 1024.0}
    for suffix, m in mult.items():
        if v.endswith(suffix):
            try:
                return float(v[: -len(suffix)]) * m
            except ValueError:
                return None
    return None


def read_stats(path: str, t0_ms: float = 0, t1_ms: float = 0) -> dict:
    """docker-stats CSV -> broker CPU (avg/peak) and peak memory.

    When a window is given, only samples inside it are used, so the server-side
    numbers cover the same slice of time as the client-side ones.
    """
    cpu: list[float] = []
    mem: list[float] = []
    epochs: list[int] = []
    windowed = 0
    for r in csv.DictReader(Path(path).open(encoding="utf-8", errors="replace")):
        if r.get("container") != BROKER:
            continue
        epoch = r.get("epoch", "")
        if epoch.isdigit():
            epochs.append(int(epoch))
        if t1_ms and epoch.isdigit():
            e_ms = int(epoch) * 1000
            if e_ms < t0_ms or e_ms > t1_ms:
                continue
            windowed += 1
        try:
            cpu.append(float(r["cpu_pct"]))
        except (ValueError, KeyError):
            pass
        m = _mib(r.get("mem_used", ""))
        if m is not None:
            mem.append(m)

    # A capture that does not overlap the load window measured an IDLE broker.
    # Reporting those numbers as if they were under-load figures is worse than
    # reporting nothing, so mark the run invalid instead of emitting zeros.
    valid = bool(cpu) and (windowed > 0 or not t1_ms)
    offset_s = 0
    if epochs and t0_ms:
        offset_s = int(min(epochs) - t0_ms / 1000)

    return {
        "cpu_avg": st.mean(cpu) if cpu else 0.0,
        "cpu_peak": max(cpu) if cpu else 0.0,
        "mem_peak": max(mem) if mem else 0.0,
        "samples": len(cpu),
        "windowed": windowed,
        "valid": valid,
        "offset_s": offset_s,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--jtl")
    ap.add_argument("--stats")
    ap.add_argument(
        "--warmup",
        type=float,
        default=60.0,
        help="seconds of ramp-up to discard before measuring (default 60; use 0 to keep all)",
    )
    a = ap.parse_args()

    j = read_jtl(a.jtl, a.warmup) if a.jtl and Path(a.jtl).exists() else None
    s = None
    if a.stats and Path(a.stats).exists():
        s = read_stats(a.stats, j["t0_ms"] if j else 0, j["t1_ms"] if j else 0)

    print(f"\n=== {a.label} ===")
    if j and j["appended_s"]:
        print(
            f"  ! this .jtl holds MORE THAN ONE run (idle gap of {j['appended_s']:.0f}s inside it)."
        )
        print("    'jmeter -l' appends to an existing file - only the LAST run is summarized.")
        print("    Delete the .jtl before re-running a scale, or write to a new filename.")
    if j:
        print(
            f"  conns  : {j['conn_ok']} established"
            + (f" | {j['conn_real_fail']} FAILED" if j["conn_real_fail"] else "")
            + (f" | {j['conn_artifact']} re-connect artefacts ignored" if j["conn_artifact"] else "")
        )
        print(
            f"  client : {j['pub_ok']} publishes over {j['window_s']:.0f}s "
            f"(warm-up {a.warmup:.0f}s discarded) | {j['thrpt']:.0f} msg/s | "
            f"{j['mbps']:.2f} MB/s | err {j['err_pct']:.3f}%"
        )
        print(
            f"  latency: p50={j['p50']:.0f}  p95={j['p95']:.0f}  p99={j['p99']:.0f}  "
            f"max={j['max']:.0f} ms   (publish ack, QoS-level - NOT end-to-end)"
        )
    if s and s["valid"]:
        scope = f"{s['windowed']} samples in window" if s["windowed"] else f"{s['samples']} samples, whole file"
        print(
            f"  broker : CPU avg {s['cpu_avg']:.1f}% / peak {s['cpu_peak']:.1f}% | "
            f"mem peak {s['mem_peak']:.1f} MiB   ({scope})"
        )
    elif s:
        print(
            f"  broker : n/a - capture-stats did not overlap the load "
            f"(started {s['offset_s']:+d}s relative to the measurement window)"
        )
        print("           Those samples measured an IDLE broker. Re-run this scale with")
        print("           capture-stats.sh started BEFORE jmeter, in a parallel terminal.")

    if j and j["conn_real_fail"]:
        print(
            f"  ! {j['conn_real_fail']} genuine connection failures - check whether the broker or the "
            f"generator hit its ceiling (compare broker CPU against host CPU)"
        )

    # one markdown table row for BENCHMARK.md
    if j:
        cpu_cell = f"{s['cpu_peak']:.0f}%" if s and s["valid"] else "n/a"
        mem_cell = f"{s['mem_peak']:.0f} MiB" if s and s["valid"] else "n/a"
        print(
            f"\n| {a.label} | {j['conn_ok']} | {j['thrpt']:.0f} | {j['mbps']:.2f} | {j['p50']:.0f} | "
            f"{j['p95']:.0f} | {j['p99']:.0f} | {j['max']:.0f} | {j['err_pct']:.3f}% | "
            f"{cpu_cell} | {mem_cell} |"
        )


if __name__ == "__main__":
    main()
