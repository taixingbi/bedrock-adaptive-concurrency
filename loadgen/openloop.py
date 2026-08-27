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
    tenant_id: str = "default"
    mix: dict[str, float] | None = None


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


def pick_prompt_class(phase: Phase, rng: random.Random | None = None) -> str:
    mix = phase.mix
    if not mix:
        return phase.prompt_class
    r = (rng or random).random()
    acc = 0.0
    items = list(mix.items())
    for i, (cls, frac) in enumerate(items):
        acc += float(frac)
        if r <= acc or i == len(items) - 1:
            return str(cls)
    return phase.prompt_class


def next_phase_start(phases: list[Phase], elapsed: float, duration_s: float) -> float:
    for phase in phases:
        if phase.until_s > elapsed:
            return min(float(phase.until_s), duration_s)
    return duration_s


def freeze_class(phase: Phase, prompt_class: str) -> Phase:
    return Phase(
        until_s=phase.until_s,
        rps=phase.rps,
        concurrency=phase.concurrency,
        prompt_class=prompt_class,
        input_tokens=phase.input_tokens,
        max_tokens=phase.max_tokens,
        tenant_id=phase.tenant_id,
        mix=None,
    )


def build_schedule(phases: list[Phase], duration_s: float, rng: random.Random) -> list[tuple[float, Phase]]:
    """Deterministic open-loop arrivals so policies in the same rep share a trace."""
    t = 0.0
    out: list[tuple[float, Phase]] = []
    while t < duration_s:
        phase = phase_at(phases, t)
        rps = max(float(phase.rps or 0.0), 0.0)
        if rps <= 0:
            nxt = next_phase_start(phases, t, duration_s)
            if nxt <= t:
                break
            t = nxt
            continue
        out.append((t, freeze_class(phase, pick_prompt_class(phase, rng))))
        t += 1.0 / rps
    return out


def phase_from_dict(raw: dict[str, Any], defaults: Phase | None = None) -> Phase:
    base = defaults or Phase(until_s=0)
    return Phase(
        until_s=float(raw.get("until_s", base.until_s)),
        rps=raw.get("rps", base.rps),
        concurrency=raw.get("concurrency", base.concurrency),
        prompt_class=raw.get("prompt_class", base.prompt_class),
        input_tokens=raw.get("input_tokens", base.input_tokens),
        max_tokens=raw.get("max_tokens", base.max_tokens),
        tenant_id=str(raw.get("tenant_id", base.tenant_id)),
        mix=raw.get("mix", base.mix),
    )


async def _one_request(client: httpx.AsyncClient, url: str, phase: Phase, stats: LoadStats) -> None:
    prompt_class = pick_prompt_class(phase)
    body: dict[str, Any] = {
        "prompt_class": prompt_class,
        "temperature": 0,
        "tenant_id": phase.tenant_id,
    }
    if phase.input_tokens is not None and not phase.mix:
        body["input_tokens"] = phase.input_tokens
    if phase.max_tokens is not None and not phase.mix:
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
    trace_seed: int | None = None,
) -> None:
    start = time.time()
    pending: set[asyncio.Task] = set()
    rng = random.Random(trace_seed) if trace_seed is not None else None
    schedule = None if rng is None else build_schedule(phases, duration_s, rng)

    async with httpx.AsyncClient() as client:
        if schedule is not None:
            for launch_t, phase in schedule:
                delay = launch_t - (time.time() - start)
                if delay > 0:
                    await asyncio.sleep(delay)
                if time.time() - start >= duration_s:
                    break
                task = asyncio.create_task(_one_request(client, url, phase, stats))
                pending.add(task)
                task.add_done_callback(pending.discard)
        else:
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
    stats = LoadStats()
    url = args.url.rstrip("/") + "/v1/infer"
    poisson = bool(getattr(args, "poisson", False))
    if getattr(args, "streams", None):
        parsed = [[phase_from_dict(p) for p in stream] for stream in args.streams if stream]
        duration = max((ph.until_s for stream in parsed for ph in stream), default=args.warmup_s + args.measure_s)
        if args.mode == "closed_loop":
            stream = parsed[0]
            concurrency = args.concurrency or stream[0].concurrency or 1
            await run_closed_loop(
                url=url, concurrency=concurrency, duration_s=duration, phases=stream, stats=stats
            )
            return stats
        base_seed = getattr(args, "trace_seed", None)
        await asyncio.gather(
            *[
                run_open_loop(
                    url=url,
                    duration_s=duration,
                    phases=stream,
                    stats=stats,
                    poisson=poisson,
                    trace_seed=None if base_seed is None else int(base_seed) + i,
                )
                for i, stream in enumerate(parsed)
            ]
        )
        return stats
    if args.phases:
        phases = [phase_from_dict(p, Phase(until_s=0, prompt_class=args.prompt_class)) for p in args.phases]
    else:
        phases = [
            Phase(
                until_s=args.warmup_s + args.measure_s,
                rps=args.rps,
                concurrency=args.concurrency,
                prompt_class=args.prompt_class,
                input_tokens=args.input_tokens,
                max_tokens=args.max_tokens,
                tenant_id=getattr(args, "tenant_id", "default"),
            )
        ]
    duration = args.warmup_s + args.measure_s
    if args.mode == "closed_loop":
        concurrency = args.concurrency or phases[0].concurrency or 1
        await run_closed_loop(url=url, concurrency=concurrency, duration_s=duration, phases=phases, stats=stats)
    else:
        await run_open_loop(
            url=url,
            duration_s=duration,
            phases=phases,
            stats=stats,
            poisson=poisson,
            trace_seed=getattr(args, "trace_seed", None),
        )
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
    p.add_argument("--tenant-id", default="default")
    p.add_argument("--poisson", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.phases = None
    args.streams = None
    stats = asyncio.run(run(args))
    print(
        f"launched={stats.launched} completed={stats.completed} "
        f"ok={stats.ok} reject={stats.reject} error={stats.error}"
    )


if __name__ == "__main__":
    main()
