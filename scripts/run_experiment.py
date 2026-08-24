#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.knee import find_knee
from analysis.metrics import load_events, summarize
from analysis.plot import plot_e1, plot_timeseries
from analysis.quota import (
    BEDROCK_RPM_QUOTA,
    BEDROCK_TPM_QUOTA,
    BEDROCK_TPD_QUOTA,
    published_envelopes,
    warn_rps,
)
from loadgen.openloop import Phase, run as run_load


def load_spec(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def expand_spec(spec: dict[str, Any], derived: dict[str, Any]) -> dict[str, Any]:
    r_knee = float(derived.get("r_knee") or spec.get("r_knee") or 0.0)
    c_knee = derived.get("c_knee") if derived.get("c_knee") is not None else spec.get("c_knee")
    for phase in spec.get("phases") or []:
        if phase.get("rps") is None and phase.get("rps_frac") is not None:
            phase["rps"] = float(phase["rps_frac"]) * r_knee
        if phase.get("prompt_class") is None:
            phase["prompt_class"] = spec.get("workload", {}).get("prompt_class", "short")
    if spec.get("experiment") == "E5" or spec.get("capacity_ref") == "quota":
        spec["_quota_cap_rps"] = published_envelopes()["short"]["rps_cap"]
    if spec.get("offered_rps") is None and spec.get("rps_frac") is not None:
        spec["offered_rps"] = float(spec["rps_frac"]) * r_knee
    spec["_derived"] = {"r_knee": r_knee, "c_knee": c_knee, **derived}
    for phase in spec.get("phases") or []:
        if phase.get("rps") is None:
            continue
        msg = warn_rps(float(phase["rps"]), phase.get("prompt_class", "short"))
        if msg:
            print(f"quota warning: {msg}")
    return spec


def wait_health(url: str, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            resp = httpx.get(url.rstrip("/") + "/health", timeout=2.0)
            if resp.status_code == 200:
                return
            last = resp.text
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"gateway did not become healthy: {last}")


def start_gateway(env: dict[str, str], port: int) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    full_env = os.environ.copy()
    full_env.update(env)
    full_env["PYTHONPATH"] = str(ROOT / "gateway") + os.pathsep + full_env.get("PYTHONPATH", "")
    return subprocess.Popen(cmd, cwd=str(ROOT), env=full_env)


def stop_gateway(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def cell_env(spec: dict[str, Any], cell: dict[str, Any], run_id: str, args: argparse.Namespace) -> dict[str, str]:
    settings = spec.get("gateway") or {}
    merged = {**settings, **{k: v for k, v in cell.items() if k != "name"}}
    env = {
        "POLICY": str(merged.get("policy", spec.get("policy", "fixed"))),
        "CONCURRENCY_LIMIT": str(merged.get("concurrency_limit", merged.get("c", spec.get("c", 8)))),
        "C_MIN": str(merged.get("c_min", 1)),
        "C_MAX": str(merged.get("c_max", args.c_max or 64)),
        "TTFT_SLO_MS": str(merged.get("ttft_slo_ms", args.slo_ms or spec.get("ttft_slo_ms") or 2000)),
        "RESULTS_PATH": str(args.results),
        "RUN_ID": run_id,
        "MOCK_BEDROCK": "true" if args.mock else "false",
        "CONTROLLER_WINDOW_S": str(merged.get("controller_window_s", 5)),
        "USE_TOKEN_AWARENESS": str(merged.get("use_token_awareness", True)).lower(),
        "USE_TTFT_SIGNAL": str(merged.get("use_ttft_signal", True)).lower(),
        "USE_THROTTLE_SIGNAL": str(merged.get("use_throttle_signal", True)).lower(),
        "USE_MULTIPLICATIVE_DECREASE": str(merged.get("use_multiplicative_decrease", True)).lower(),
        "USE_DEMAND_GATE": str(merged.get("use_demand_gate", spec.get("use_demand_gate", True))).lower(),
        "BEDROCK_RPM_QUOTA": str(merged.get("bedrock_rpm_quota", BEDROCK_RPM_QUOTA)),
        "BEDROCK_TPM_QUOTA": str(merged.get("bedrock_tpm_quota", BEDROCK_TPM_QUOTA)),
        "BEDROCK_TPD_QUOTA": str(merged.get("bedrock_tpd_quota", BEDROCK_TPD_QUOTA)),
        "QUEUE_MAX": str(merged.get("queue_max", spec.get("queue_max", 16))),
        "QUEUE_TIMEOUT_S": str(merged.get("queue_timeout_s", spec.get("queue_timeout_s", 2.0))),
        "MODEL_ID": str(merged.get("model_id", "us.meta.llama4-maverick-17b-instruct-v1:0")),
        "AWS_REGION": str(merged.get("aws_region", "us-east-1")),
    }
    return env


def phases_for(spec: dict[str, Any], cell: dict[str, Any]) -> list[Phase]:
    warmup = float(spec.get("warmup_s", 0))
    measure = float(spec.get("measure_s", 30))
    workload = spec.get("workload") or {}
    if spec.get("phases"):
        return [
            Phase(
                until_s=float(p["until_s"]),
                rps=p.get("rps"),
                concurrency=p.get("concurrency") or cell.get("c"),
                prompt_class=p.get("prompt_class", workload.get("prompt_class", "short")),
                input_tokens=p.get("input_tokens", workload.get("input_tokens")),
                max_tokens=p.get("max_tokens", workload.get("max_tokens")),
            )
            for p in spec["phases"]
        ]
    return [
        Phase(
            until_s=warmup + measure,
            rps=cell.get("rps", spec.get("offered_rps")),
            concurrency=cell.get("c") or spec.get("c"),
            prompt_class=workload.get("prompt_class", "short"),
            input_tokens=workload.get("input_tokens"),
            max_tokens=workload.get("max_tokens"),
        )
    ]


def cells_from_spec(spec: dict[str, Any], derived: dict[str, Any]) -> list[dict[str, Any]]:
    if spec.get("cells"):
        return list(spec["cells"])
    experiment = spec.get("experiment", "")
    if experiment == "E1" or spec.get("concurrency"):
        return [{"name": f"c{c}", "policy": "fixed", "c": int(c)} for c in spec["concurrency"]]
    if experiment == "E2":
        if derived.get("c_knee") is None:
            raise SystemExit("E2 needs --c-knee from E1")
        c_knee = int(derived["c_knee"])
        c_low = max(1, c_knee // 2)
        cells = []
        if c_low != c_knee:
            cells.append({"name": "fixed_low", "policy": "fixed", "c": c_low})
        cells.extend(
            [
                {"name": "fixed_knee", "policy": "fixed", "c": c_knee},
                {"name": "fixed_high", "policy": "fixed", "c": max(c_knee * 2, c_knee + 1)},
                {"name": "retry_backoff", "policy": "retry_backoff", "c": max(c_knee * 2, c_knee + 1)},
                {"name": "gradient", "policy": "gradient", "c": c_knee},
                {"name": "slo_aimd", "policy": "slo_aimd", "c": c_knee},
            ]
        )
        return cells
    if experiment == "E6":
        c0 = int(derived.get("c_knee") or spec.get("c") or 8)
        return [
            {"name": "full", "policy": "token_slo_aimd", "c": c0},
            {"name": "minus_token", "policy": "token_slo_aimd", "c": c0, "use_token_awareness": False},
            {"name": "minus_ttft", "policy": "token_slo_aimd", "c": c0, "use_ttft_signal": False},
            {"name": "minus_throttle", "policy": "token_slo_aimd", "c": c0, "use_throttle_signal": False},
            {"name": "minus_md", "policy": "token_slo_aimd", "c": c0, "use_multiplicative_decrease": False},
        ]
    if experiment == "E5" or spec.get("capacity_ref") == "quota":
        cap = float(spec.get("_quota_cap_rps") or published_envelopes()["short"]["rps_cap"])
        c0 = int(derived.get("c_knee") or spec.get("c") or 8)
        cells = []
        for policy in spec.get("policies") or ["slo_aimd"]:
            name = policy if isinstance(policy, str) else policy.get("name")
            for frac in spec.get("load_frac") or [1.0]:
                cells.append(
                    {
                        "name": f"{name}_f{frac}",
                        "policy": name if isinstance(policy, str) else policy.get("policy", name),
                        "c": c0,
                        "rps": float(frac) * cap,
                    }
                )
        return cells
    policies = spec.get("policies") or [spec.get("policy", "slo_aimd")]
    loads = spec.get("load_frac") or [spec.get("rps_frac") or 1.0]
    c0 = derived.get("c_knee") or spec.get("c") or 8
    cells = []
    for policy in policies:
        name = policy if isinstance(policy, str) else policy.get("name")
        for frac in loads:
            cells.append(
                {
                    "name": f"{name}_f{frac}",
                    "policy": name if isinstance(policy, str) else policy.get("policy", name),
                    "c": int(c0),
                    "rps": float(frac) * float(derived.get("r_knee") or 0.0),
                    **({} if isinstance(policy, str) else policy),
                }
            )
    return cells


class _Args:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def run_cell(spec: dict[str, Any], cell: dict[str, Any], args: argparse.Namespace, rep: int) -> dict[str, Any]:
    run_id = f"{spec['name']}/{cell['name']}/rep{rep}"
    port = args.port
    url = f"http://127.0.0.1:{port}"
    env = cell_env(spec, cell, run_id, args)
    proc = start_gateway(env, port)
    try:
        wait_health(url)
        phases = phases_for(spec, cell)
        duration = float(spec.get("warmup_s", 0)) + float(spec.get("measure_s", 30))
        if spec.get("phases"):
            duration = max(p.until_s for p in phases)
        load_args = _Args(
            url=url,
            mode=spec.get("mode", "open_loop"),
            rps=cell.get("rps") or spec.get("offered_rps") or 1.0,
            concurrency=int(cell.get("c") or spec.get("c") or 1),
            warmup_s=0.0,
            measure_s=duration,
            prompt_class=(spec.get("workload") or {}).get("prompt_class", "short"),
            input_tokens=(spec.get("workload") or {}).get("input_tokens"),
            max_tokens=(spec.get("workload") or {}).get("max_tokens"),
            poisson=bool(spec.get("poisson", False)),
            phases=[
                {
                    "until_s": p.until_s,
                    "rps": p.rps,
                    "concurrency": p.concurrency,
                    "prompt_class": p.prompt_class,
                    "input_tokens": p.input_tokens,
                    "max_tokens": p.max_tokens,
                }
                for p in phases
            ],
        )
        asyncio.run(run_load(load_args))
    finally:
        stop_gateway(proc)
    result_dir = Path(args.results) / run_id
    events = load_events(result_dir)
    summary = summarize(events, warmup_s=float(spec.get("warmup_s", 0)))
    summary["cell"] = cell["name"]
    summary["rep"] = rep
    summary["c"] = cell.get("c")
    summary["policy"] = env["POLICY"]
    (result_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--results", default="results")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--c-knee", type=int, default=None)
    parser.add_argument("--r-knee", type=float, default=None)
    parser.add_argument("--slo-ms", type=float, default=None)
    parser.add_argument("--c-max", type=int, default=None)
    parser.add_argument("--reps", type=int, default=None)
    parser.add_argument("--plot", action="store_true", help="Write matplotlib PNGs after the run")
    args = parser.parse_args()

    spec = expand_spec(
        load_spec(Path(args.spec)),
        {"c_knee": args.c_knee, "r_knee": args.r_knee, "slo_ms": args.slo_ms},
    )
    reps = int(args.reps or spec.get("repetitions") or 1)
    cells = cells_from_spec(spec, spec["_derived"])
    summaries: list[dict[str, Any]] = []
    for cell in cells:
        for rep in range(1, reps + 1):
            print(f"== {spec['name']} {cell['name']} rep{rep} ==")
            summaries.append(run_cell(spec, cell, args, rep))

    out_dir = Path(args.results) / spec["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"spec": spec["name"], "summaries": summaries}
    if spec.get("experiment") == "E1":
        by_c: dict[int, list[dict[str, Any]]] = {}
        for row in summaries:
            by_c.setdefault(int(row["c"]), []).append(row)
        points = []
        for c, rows in sorted(by_c.items()):
            points.append(
                {
                    "c": c,
                    "throughput_rps": sum(r["throughput_rps"] for r in rows) / len(rows),
                    "p95_ttft_ms": sum((r.get("p95_ttft_ms") or 0) for r in rows) / len(rows),
                    "slo_goodput_rps": sum(r.get("slo_goodput_rps") or 0 for r in rows) / len(rows),
                }
            )
        payload["knee"] = find_knee(points)
        if args.plot:
            try:
                plot_e1(points, out_dir / "e1_knee.png")
            except Exception as exc:  # noqa: BLE001
                print(f"e1 plot skipped: {exc}")
        print(json.dumps(payload["knee"], indent=2))
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    series_dir = Path(args.results) / spec["name"]
    if args.plot and summaries:
        last = Path(args.results) / spec["name"] / summaries[-1]["cell"] / f"rep{summaries[-1]['rep']}"
        from analysis.metrics import load_timeseries

        try:
            plot_timeseries(load_timeseries(last), series_dir / "timeseries.png")
        except Exception as exc:  # noqa: BLE001
            print(f"timeseries plot skipped: {exc}")


if __name__ == "__main__":
    main()
