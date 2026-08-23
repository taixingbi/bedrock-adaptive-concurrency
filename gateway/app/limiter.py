from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class AcquireResult:
    ok: bool
    reason: str
    waited_s: float = 0.0


class ConcurrencyLimiter:
    """Dynamic max-in-flight limiter with a bounded wait queue."""

    def __init__(self, limit: int, queue_max: int) -> None:
        self._limit = max(int(limit), 1)
        self._queue_max = max(int(queue_max), 0)
        self._inflight = 0
        self._waiting = 0
        self._w_t = 0.0
        self._cond = asyncio.Condition()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def inflight(self) -> int:
        return self._inflight

    @property
    def waiting(self) -> int:
        return self._waiting

    @property
    def w_t(self) -> float:
        return self._w_t

    async def set_limit(self, limit: int) -> None:
        async with self._cond:
            self._limit = max(int(limit), 1)
            self._cond.notify_all()

    def set_limit_nowait(self, limit: int) -> None:
        self._limit = max(int(limit), 1)

    async def acquire(self, weight: float, timeout_s: float | None = None) -> AcquireResult:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        async with self._cond:
            if self._inflight >= self._limit and self._waiting >= self._queue_max:
                return AcquireResult(ok=False, reason="queue_full")
            self._waiting += 1
            try:
                while self._inflight >= self._limit:
                    if timeout_s is None:
                        await self._cond.wait()
                        continue
                    remaining = timeout_s - (loop.time() - t0)
                    if remaining <= 0:
                        return AcquireResult(ok=False, reason="queue_timeout", waited_s=loop.time() - t0)
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=remaining)
                    except TimeoutError:
                        return AcquireResult(ok=False, reason="queue_timeout", waited_s=loop.time() - t0)
                self._inflight += 1
                self._w_t += float(weight)
            finally:
                self._waiting -= 1
        return AcquireResult(ok=True, reason="admitted", waited_s=loop.time() - t0)

    async def release(self, weight: float) -> None:
        async with self._cond:
            self._inflight = max(0, self._inflight - 1)
            self._w_t = max(0.0, self._w_t - float(weight))
            self._cond.notify_all()
