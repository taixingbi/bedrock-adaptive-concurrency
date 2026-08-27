from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    files = [path] if path.is_file() else sorted(path.rglob("*.jsonl"))
    for file in files:
        if file.name == "timeseries.jsonl":
            continue
        for line in file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def load_timeseries(path: Path) -> list[dict[str, Any]]:
    target = path if path.name == "timeseries.jsonl" else path / "timeseries.jsonl"
    if not target.is_file():
        return []
    return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[idx]


def filter_warmup(events: list[dict[str, Any]], warmup_s: float) -> list[dict[str, Any]]:
    if not events or warmup_s <= 0:
        return events
    t0 = min(float(e["arrival_ts"]) for e in events if e.get("arrival_ts") is not None)
    return [e for e in events if e.get("arrival_ts") is not None and float(e["arrival_ts"]) >= t0 + warmup_s]


def summarize(events: list[dict[str, Any]], *, warmup_s: float = 0.0) -> dict[str, Any]:
    rows = filter_warmup(events, warmup_s)
    n = len(rows)
    if n == 0:
        return {"requests": 0}
    t0 = min(float(e["arrival_ts"]) for e in rows)
    t1 = max(float(e.get("finish_ts") or e["arrival_ts"]) for e in rows)
    duration = max(t1 - t0, 1e-6)
    admitted = [e for e in rows if e.get("decision") == "ADMIT"]
    achieved = [
        e
        for e in admitted
        if e.get("ttft_ms") is not None and not e.get("bedrock_429") and not e.get("bedrock_5xx")
    ]
    ttfts = [float(e["ttft_ms"]) for e in achieved if e.get("ttft_ms") is not None]
    e2e = [float(e["e2e_ms"]) for e in achieved if e.get("e2e_ms") is not None]
    slo_n = sum(1 for e in achieved if e.get("slo_met"))
    rejects = [e for e in rows if e.get("decision") == "REJECT"]
    reject_reasons = dict(Counter(str(e.get("reason") or "unknown") for e in rejects))
    return {
        "requests": n,
        "duration_s": duration,
        "admit_n": len(admitted),
        "reject_n": len(rejects),
        "reject_by_reason": reject_reasons,
        "completion_rate": len(achieved) / n,
        "achieved_n": len(achieved),
        "throughput_rps": len(achieved) / duration,
        "slo_goodput_rps": slo_n / duration,
        "slo_attainment": slo_n / max(len(achieved), 1),
        "p50_ttft_ms": percentile(ttfts, 0.50),
        "p95_ttft_ms": percentile(ttfts, 0.95),
        "p99_ttft_ms": percentile(ttfts, 0.99),
        "p95_e2e_ms": percentile(e2e, 0.95),
        "p99_e2e_ms": percentile(e2e, 0.99),
        "bedrock_429_n": sum(1 for e in rows if e.get("bedrock_429")),
        "bedrock_5xx_n": sum(1 for e in rows if e.get("bedrock_5xx")),
        "bedrock_429_rate": sum(1 for e in rows if e.get("bedrock_429")) / n,
        "bedrock_5xx_rate": sum(1 for e in rows if e.get("bedrock_5xx")) / n,
        "input_tokens": sum(int(e.get("input_tokens") or 0) for e in rows),
        "output_tokens": sum(int(e.get("output_tokens") or 0) for e in rows),
        "input_tps": sum(int(e.get("input_tokens") or 0) for e in rows) / duration,
        "output_tps": sum(int(e.get("output_tokens") or 0) for e in rows) / duration,
        "mean_c": _mean([e.get("c_limit") for e in rows]),
        "retries": sum(int(e.get("retries") or 0) for e in rows),
    }


def tenant_class_key(event: dict[str, Any]) -> str:
    return f"{event.get('tenant_id') or 'default'}:{event.get('prompt_class') or 'short'}"


def summarize_groups(
    events: list[dict[str, Any]],
    *,
    key: str | None = None,
    key_fn: Callable[[dict[str, Any]], str] | None = None,
    warmup_s: float = 0.0,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in filter_warmup(events, warmup_s):
        if key_fn is not None:
            name = key_fn(event)
        else:
            name = str(event.get(key) or "default")
        grouped.setdefault(name, []).append(event)
    return {name: summarize(rows) for name, rows in grouped.items()}


def _mean(values: list[Any]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)
