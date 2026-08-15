#!/usr/bin/env python3
"""MAGRIS · turn the benchmark sweeps into charts.

Reads the same `.jtl` / `docker stats` files as `summarize.py` — and reuses its
parsing, so a number on a chart is always the number in the table — and writes
PNGs for the two sweeps:

  chart-device-sweep.png   throughput / latency / resources vs device count
  chart-rate-sweep.png     the saturation curve: offered vs achieved load

Usage:
  python bench/plot.py
  python bench/plot.py --out results/charts --note "PROVISIONAL - see BENCHMARK.md"

`--note` stamps a caption on every figure. Use it whenever the underlying runs
are not clean; an unlabelled chart outlives the caveat that came with it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in this environment
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from summarize import read_jtl, read_stats  # noqa: E402

DEVICE_SCALES = [100, 300, 600, 1000, 1500, 2000, 3000, 4000, 5000, 6000]
RATE_POINTS = [2000, 1000, 500, 250, 100]  # rate_ms, all at 4000 devices
RATE_DEVICES = 4000

INK = "#1b1b1b"
ACCENT = "#6d3bdc"
WARN = "#c2410c"
MUTED = "#8a8a8a"


def _collect(jtl: Path, stats: Path, warmup: float) -> dict | None:
    if not jtl.exists():
        return None
    j = read_jtl(str(jtl), warmup)
    if j is None:
        return None
    s = read_stats(str(stats), j["t0_ms"], j["t1_ms"]) if stats.exists() else None
    j["cpu_peak"] = s["cpu_peak"] if s and s["valid"] else None
    j["mem_peak"] = s["mem_peak"] if s and s["valid"] else None
    return j


def _style(ax, xlabel: str, ylabel: str, title: str) -> None:
    ax.set_title(title, fontsize=11, color=INK, loc="left", pad=8)
    ax.set_xlabel(xlabel, fontsize=9, color=MUTED)
    ax.set_ylabel(ylabel, fontsize=9, color=MUTED)
    ax.grid(True, alpha=0.25, linewidth=0.6)
    ax.tick_params(labelsize=8, colors=MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def _caption(fig, note: str) -> None:
    """Stamp a caption under the figure, wrapped so long notes are not clipped."""
    if not note:
        return
    fig.text(0.5, 0.012, note, ha="center", va="bottom", fontsize=8, color=WARN,
             weight="bold", wrap=True)


def device_sweep(results_dir: Path, out: Path, warmup: float, note: str) -> Path | None:
    rows = []
    for n in DEVICE_SCALES:
        d = _collect(results_dir / f"jmeter-{n}.jtl", results_dir / f"stats-{n}dev.csv", warmup)
        if d:
            rows.append((n, d))
    if not rows:
        return None

    x = [n for n, _ in rows]
    fig, axes = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

    axes[0].plot(x, [d["thrpt"] for _, d in rows], "o-", color=ACCENT, lw=1.8, ms=5)
    axes[0].plot(x, [n / 2 for n in x], "--", color=MUTED, lw=1.2, label="target (devices / 2)")
    axes[0].legend(fontsize=8, frameon=False)
    _style(axes[0], "", "msg/s", "Throughput scales linearly with device count")

    for key, lbl, style in (("p50", "p50", "o-"), ("p95", "p95", "s-"), ("p99", "p99", "^-")):
        axes[1].plot(x, [d[key] for _, d in rows], style, lw=1.6, ms=4, label=lbl)
    axes[1].legend(fontsize=8, frameon=False)
    _style(axes[1], "", "publish-ack latency (ms)", "Latency stays flat — no saturation on this axis")

    cpu = [d["cpu_peak"] for _, d in rows]
    axes[2].plot(x, cpu, "o-", color=WARN, lw=1.8, ms=5, label="broker CPU peak (%)")
    ax2 = axes[2].twinx()
    ax2.plot(x, [d["mem_peak"] for _, d in rows], "s--", color=MUTED, lw=1.4, ms=4,
             label="broker mem peak (MiB)")
    ax2.set_ylabel("MiB", fontsize=9, color=MUTED)
    ax2.tick_params(labelsize=8, colors=MUTED)
    ax2.spines["top"].set_visible(False)
    _style(axes[2], "concurrent devices (= MQTT connections)", "CPU %", "Broker cost grows gently")
    h1, l1 = axes[2].get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    axes[2].legend(h1 + h2, l1 + l2, fontsize=8, frameon=False, loc="upper left")

    fig.suptitle("Variant A — device-count sweep (rate_ms = 2000)", fontsize=13, color=INK, x=0.06,
                 ha="left", weight="bold")
    fig.tight_layout(rect=(0, 0.045, 1, 0.97))
    _caption(fig, note)
    path = out / "chart-device-sweep.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def rate_sweep(results_dir: Path, out: Path, warmup: float, note: str) -> Path | None:
    rows = []
    for rate_ms in RATE_POINTS:
        if rate_ms == 2000:  # the 4000-device point of the other sweep, same config
            jtl, stats = results_dir / "jmeter-4000.jtl", results_dir / "stats-4000dev.csv"
        else:
            jtl = results_dir / f"jmeter-{RATE_DEVICES}-r{rate_ms}.jtl"
            stats = results_dir / f"stats-{RATE_DEVICES}dev-r{rate_ms}.csv"
        d = _collect(jtl, stats, warmup)
        if not d:
            continue
        offered = RATE_DEVICES / (rate_ms / 1000)
        # A run cannot deliver meaningfully more than it was asked for. When it
        # appears to, the file does not hold the run its name claims — usually
        # overwritten by a later run with the wrong -l argument. Drop it loudly
        # rather than drawing an impossible curve.
        if d["thrpt"] > offered * 1.2:
            print(
                f"  ! SKIPPED {jtl.name}: achieved {d['thrpt']:,.0f} msg/s but only "
                f"{offered:,.0f} msg/s was offered (rate_ms={rate_ms}). This file does not "
                f"contain the run its name implies — re-run that point.",
                file=sys.stderr,
            )
            continue
        d["offered"] = offered
        rows.append((rate_ms, d))
    if not rows:
        return None

    rows.sort(key=lambda r: r[1]["offered"])
    offered = [d["offered"] for _, d in rows]
    achieved = [d["thrpt"] for _, d in rows]

    fig, axes = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

    axes[0].plot(offered, offered, "--", color=MUTED, lw=1.2, label="ideal (achieved = offered)")
    axes[0].plot(offered, achieved, "o-", color=ACCENT, lw=1.8, ms=6, label="achieved")
    ceiling = max(achieved)
    axes[0].axhline(ceiling, color=WARN, lw=1.0, ls=":", label=f"ceiling ≈ {ceiling:,.0f} msg/s")
    axes[0].set_xscale("log")
    axes[0].legend(fontsize=8, frameon=False)
    _style(axes[0], "", "msg/s", "Throughput plateaus — the broker stops keeping up")

    for key, lbl, style in (("p50", "p50", "o-"), ("p95", "p95", "s-"), ("p99", "p99", "^-")):
        axes[1].plot(offered, [d[key] for _, d in rows], style, lw=1.6, ms=5, label=lbl)
    axes[1].set_xscale("log")
    axes[1].set_yscale("log")
    axes[1].legend(fontsize=8, frameon=False)
    _style(axes[1], "", "publish-ack latency (ms, log)", "Latency turns non-linear at the same point")

    axes[2].plot(offered, [d["cpu_peak"] for _, d in rows], "o-", color=WARN, lw=1.8, ms=6)
    axes[2].axhline(100, color=INK, lw=1.0, ls=":", label="one CPU core (mosquitto is single-threaded)")
    axes[2].set_xscale("log")
    axes[2].legend(fontsize=8, frameon=False)
    _style(axes[2], "offered load (msg/s, log scale)", "CPU %", "Broker CPU pegs at one core")

    fig.suptitle(f"Variant A — message-rate sweep ({RATE_DEVICES} devices)", fontsize=13,
                 color=INK, x=0.06, ha="left", weight="bold")
    fig.tight_layout(rect=(0, 0.045, 1, 0.97))
    _caption(fig, note)
    path = out / "chart-rate-sweep.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(here / "results"))
    ap.add_argument("--out", default=str(here / "results" / "charts"))
    ap.add_argument("--warmup", type=float, default=60.0)
    ap.add_argument("--note", default="", help="caption stamped on every figure")
    a = ap.parse_args()

    results_dir, out = Path(a.results), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    for fn in (device_sweep, rate_sweep):
        p = fn(results_dir, out, a.warmup, a.note)
        print(f"wrote {p}" if p else f"skipped {fn.__name__} — no matching result files")


if __name__ == "__main__":
    main()
