from __future__ import annotations

import argparse
import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Phase:
    until_s: float
    rps: float | None = None
    concurrency: int | None = None
    prompt_class: str = "short"
    input_tokens: int | None = None
    max_tokens: int | None = None


@dataclass
class LoadStats:
    launched: int = 0
    completed: int = 0
    ok: int = 0
    reject: int = 0
    error: int = 0


def phase_at(phases: list[Phase], elapsed: float) -> Phase:
    for phase in phases:
        if elapsed < phase.until_s:
            return phase
    return phases[-1]


async def _one_request(client: httpx.AsyncClient, url: str, phase: Phase, stats: LoadStats) -> None:
    body: dict[str, Any] = {
        "prompt_class": phase.prompt_class,
        "temperature": 0,
    }
    if phase.input_tokens is not None:
        body["input_tokens"] = phase.input_tokens
    if phase.max_tokens is not None:
        body["max_tokens"] = phase.max_tokens
    stats.launched += 1
    try:
        resp = await client.post(url, json=body, timeout=180.0)
        stats.completed += 1
        if resp.status_code == 200:
            stats.ok += 1
        elif resp.status_code == 429:
            stats.reject += 1
        else:
            stats.error += 1
    except Exception:
        stats.completed += 1
        stats.error += 1


async def run_closed_loop(
    *,
    url: str,
    concurrency: int,
    duration_s: float,
    phases: list[Phase],
    stats: LoadStats,
) -> None:
    start = time.time()

    async def worker() -> None:
        async with httpx.AsyncClient() as client:
            while time.time() - start < duration_s:
                phase = phase_at(phases, time.time() - start)
                await _one_request(client, url, phase, stats)

    await asyncio.gather(*(worker() for _ in range(max(concurrency, 1))))


async def run_open_loop(
    *,
    url: str,
    duration_s: float,
    phases: list[Phase],
    stats: LoadStats,
    poisson: bool = False,
) -> None:
    start = time.time()
    pending: set[asyncio.Task] = set()

    async with httpx.AsyncClient() as client:
        while True:
            elapsed = time.time() - start
            if elapsed >= duration_s:
                break
            phase = phase_at(phases, elapsed)
            rps = max(float(phase.rps or 0.0), 0.0)
            if rps <= 0:
                await asyncio.sleep(0.05)
                continue
            task = asyncio.create_task(_one_request(client, url, phase, stats))
            pending.add(task)
            task.add_done_callback(pending.discard)
            interval = random.expovariate(rps) if poisson else 1.0 / rps
            await asyncio.sleep(interval)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def run(args: argparse.Namespace) -> LoadStats:
    if args.phases:
        phases = [
            Phase(
                until_s=float(p["until_s"]),
                rps=p.get("rps"),
                concurrency=p.get("concurrency"),
                prompt_class=p.get("prompt_class", args.prompt_class),
                input_tokens=p.get("input_tokens"),
                max_tokens=p.get("max_tokens"),
            )
            for p in args.phases
        ]
    else:
        phases = [
            Phase(
                until_s=args.warmup_s + args.measure_s,
                rps=args.rps,
                concurrency=args.concurrency,
                prompt_class=args.prompt_class,
                input_tokens=args.input_tokens,
                max_tokens=args.max_tokens,
            )
        ]
    duration = args.warmup_s + args.measure_s
    stats = LoadStats()
    url = args.url.rstrip("/") + "/v1/infer"
    if args.mode == "closed_loop":
        concurrency = args.concurrency or phases[0].concurrency or 1
        await run_closed_loop(url=url, concurrency=concurrency, duration_s=duration, phases=phases, stats=stats)
    else:
        await run_open_loop(url=url, duration_s=duration, phases=phases, stats=stats, poisson=args.poisson)
    return stats


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Open-loop / closed-loop load generator")
    p.add_argument("--url", default="http://127.0.0.1:8080")
    p.add_argument("--mode", choices=("open_loop", "closed_loop"), default="open_loop")
    p.add_argument("--rps", type=float, default=1.0)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--warmup-s", type=float, default=0.0)
    p.add_argument("--measure-s", type=float, default=30.0)
    p.add_argument("--prompt-class", default="short")
    p.add_argument("--input-tokens", type=int, default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--poisson", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.phases = None
    stats = asyncio.run(run(args))
    print(
        f"launched={stats.launched} completed={stats.completed} "
        f"ok={stats.ok} reject={stats.reject} error={stats.error}"
    )


if __name__ == "__main__":
    main()
