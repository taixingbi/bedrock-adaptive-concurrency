from __future__ import annotations

from typing import Any


def find_knee(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Find C_knee from E1 sweep points with throughput_rps and p95_ttft_ms."""
    rows = sorted(
        [p for p in points if p.get("c") is not None and p.get("throughput_rps") is not None],
        key=lambda p: int(p["c"]),
    )
    if not rows:
        return {"c_knee": None, "r_knee": None, "slo_ms": None}
    knee = rows[0]
    for prev, cur in zip(rows, rows[1:]):
        t0 = float(prev["throughput_rps"])
        t1 = float(cur["throughput_rps"])
        l0 = float(prev.get("p95_ttft_ms") or 0.0)
        l1 = float(cur.get("p95_ttft_ms") or 0.0)
        gain = (t1 - t0) / max(t0, 1e-6)
        lat_rise = (l1 - l0) / max(l0, 1e-6) if l0 else 0.0
        knee = cur
        if gain < 0.10 and lat_rise > 0.20:
            knee = prev
            break
        if gain < 0.05:
            knee = prev
            break
    r_knee = float(knee["throughput_rps"])
    p95 = float(knee.get("p95_ttft_ms") or 0.0)
    return {
        "c_knee": int(knee["c"]),
        "r_knee": r_knee,
        "slo_ms": 1.5 * p95 if p95 else None,
        "c_low": max(1, int(knee["c"]) // 2),
        "c_high": max(2, int(knee["c"]) * 2),
        "points": rows,
    }
