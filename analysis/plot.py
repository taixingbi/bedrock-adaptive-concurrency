from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_mpl = Path.cwd() / ".mplconfig"
_mpl.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl))
os.environ.setdefault("MPLBACKEND", "Agg")


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def plot_e1(points: list[dict[str, Any]], out: Path) -> None:
    plt = _pyplot()

    rows = sorted(points, key=lambda p: int(p["c"]))
    cs = [int(p["c"]) for p in rows]
    thr = [float(p["throughput_rps"]) for p in rows]
    p95 = [p.get("p95_ttft_ms") for p in rows]
    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.plot(cs, thr, marker="o", label="throughput")
    ax1.set_xlabel("C")
    ax1.set_ylabel("throughput (rps)")
    ax2 = ax1.twinx()
    ax2.plot(cs, p95, marker="s", color="tab:red", label="TTFT P95")
    ax2.set_ylabel("TTFT P95 (ms)")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    plt.close(fig)


def plot_timeseries(rows: list[dict[str, Any]], out: Path) -> None:
    plt = _pyplot()

    if not rows:
        return
    t0 = float(rows[0]["ts"])
    xs = [float(r["ts"]) - t0 for r in rows]
    fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    axes[0].plot(xs, [r.get("offered_rps") for r in rows], label="offered")
    axes[0].plot(xs, [r.get("achieved_rps") for r in rows], label="achieved")
    axes[0].plot(xs, [r.get("slo_goodput_rps") for r in rows], label="goodput")
    axes[0].legend()
    axes[1].plot(xs, [r.get("c") for r in rows], label="C")
    axes[1].plot(xs, [r.get("inflight") for r in rows], label="inflight")
    axes[1].legend()
    axes[2].plot(xs, [r.get("ttft_p95_ms") for r in rows], label="TTFT P95")
    axes[2].legend()
    axes[2].set_xlabel("time (s)")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    plt.close(fig)
