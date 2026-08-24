from __future__ import annotations

import asyncio
from dataclasses import dataclass


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[idx]


@dataclass
class Snapshot:
    n: int
    ttft_p95_ms: float | None
    throttle_n: int
    error_n: int
    throttle_rate: float
    error_rate: float
    slo_n: int
    achieved_n: int
    offered_n: int
    input_tokens: int
    output_tokens: int
    c: int
    inflight: int
    waiting: int
    w_t: float
    queue_p95_ms: float | None
    utilization: float = 0.0
    queue_depth: int = 0
    max_inflight: int = 0
    max_waiting: int = 0
    backend_ttft_p95_ms: float | None = None


class ObservationWindow:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._reset()

    def _reset(self) -> None:
        self._ttfts: list[float] = []
        self._backend_ttfts: list[float] = []
        self._queues: list[float] = []
        self._n = 0
        self._offered = 0
        self._throttle = 0
        self._error = 0
        self._slo = 0
        self._achieved = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._max_inflight = 0
        self._max_waiting = 0

    async def offered(self) -> None:
        async with self._lock:
            self._offered += 1

    async def sample_load(self, inflight: int, waiting: int) -> None:
        async with self._lock:
            self._max_inflight = max(self._max_inflight, int(inflight))
            self._max_waiting = max(self._max_waiting, int(waiting))

    async def observe(
        self,
        *,
        ttft_ms: float | None,
        queue_ms: float,
        throttle: bool,
        error: bool,
        slo_met: bool,
        achieved: bool,
        input_tokens: int,
        output_tokens: int,
        backend_ttft_ms: float | None = None,
    ) -> None:
        async with self._lock:
            self._n += 1
            if ttft_ms is not None:
                self._ttfts.append(float(ttft_ms))
            if backend_ttft_ms is not None:
                self._backend_ttfts.append(float(backend_ttft_ms))
            self._queues.append(float(queue_ms))
            self._throttle += int(throttle)
            self._error += int(error)
            self._slo += int(slo_met)
            self._achieved += int(achieved)
            self._input_tokens += int(input_tokens)
            self._output_tokens += int(output_tokens)

    async def flush(self, *, c: int, inflight: int, waiting: int, w_t: float) -> Snapshot:
        async with self._lock:
            n = self._n
            offered = self._offered
            snap = Snapshot(
                n=n,
                ttft_p95_ms=percentile(self._ttfts, 0.95),
                backend_ttft_p95_ms=percentile(self._backend_ttfts, 0.95),
                throttle_n=self._throttle,
                error_n=self._error,
                throttle_rate=(self._throttle / n) if n else 0.0,
                error_rate=(self._error / n) if n else 0.0,
                slo_n=self._slo,
                achieved_n=self._achieved,
                offered_n=offered,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                c=c,
                inflight=inflight,
                waiting=waiting,
                w_t=w_t,
                queue_p95_ms=percentile(self._queues, 0.95),
                utilization=(float(inflight) / max(int(c), 1)),
                queue_depth=int(waiting),
                max_inflight=max(self._max_inflight, int(inflight)),
                max_waiting=max(self._max_waiting, int(waiting)),
            )
            self._reset()
            return snap
