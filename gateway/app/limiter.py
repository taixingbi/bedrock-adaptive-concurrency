from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class AcquireResult:
    ok: bool
    reason: str
    waited_s: float = 0.0


class ConcurrencyLimiter:
    """Global in-flight limiter with optional tenant and class caps."""

    def __init__(
        self,
        limit: int,
        queue_max: int,
        *,
        tenant_caps: dict[str, int] | None = None,
        class_caps: dict[str, int] | None = None,
        use_tenant_cap: bool = False,
        use_class_cap: bool = False,
    ) -> None:
        self._limit = max(int(limit), 1)
        self._queue_max = max(int(queue_max), 0)
        self._inflight = 0
        self._waiting = 0
        self._w_t = 0.0
        self._tenant_caps = dict(tenant_caps or {})
        self._class_caps = dict(class_caps or {})
        self._use_tenant_cap = bool(use_tenant_cap)
        self._use_class_cap = bool(use_class_cap)
        self._tenant_inflight: dict[str, int] = defaultdict(int)
        self._class_inflight: dict[str, int] = defaultdict(int)
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

    @property
    def tenant_inflight(self) -> dict[str, int]:
        return dict(self._tenant_inflight)

    @property
    def class_inflight(self) -> dict[str, int]:
        return dict(self._class_inflight)

    def tenant_limit(self, tenant: str) -> int | None:
        if not self._use_tenant_cap:
            return None
        return self._tenant_caps.get(tenant)

    def class_limit(self, prompt_class: str) -> int | None:
        if not self._use_class_cap:
            return None
        return self._class_caps.get(prompt_class)

    def _tenant_ok(self, tenant: str) -> bool:
        cap = self.tenant_limit(tenant)
        if cap is None:
            return True
        return self._tenant_inflight[tenant] < cap

    def _class_ok(self, prompt_class: str) -> bool:
        cap = self.class_limit(prompt_class)
        if cap is None:
            return True
        return self._class_inflight[prompt_class] < cap

    async def set_limit(self, limit: int) -> None:
        async with self._cond:
            self._limit = max(int(limit), 1)
            self._cond.notify_all()

    def set_limit_nowait(self, limit: int) -> None:
        self._limit = max(int(limit), 1)

    async def acquire(
        self,
        weight: float,
        timeout_s: float | None = None,
        tenant: str = "default",
        prompt_class: str = "short",
    ) -> AcquireResult:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        async with self._cond:
            if not self._tenant_ok(tenant):
                return AcquireResult(ok=False, reason="tenant_full")
            if not self._class_ok(prompt_class):
                return AcquireResult(ok=False, reason="class_full")
            if self._inflight >= self._limit and self._waiting >= self._queue_max:
                return AcquireResult(ok=False, reason="queue_full")
            self._waiting += 1
            try:
                while True:
                    if not self._tenant_ok(tenant):
                        return AcquireResult(ok=False, reason="tenant_full", waited_s=loop.time() - t0)
                    if not self._class_ok(prompt_class):
                        return AcquireResult(ok=False, reason="class_full", waited_s=loop.time() - t0)
                    if self._inflight < self._limit:
                        self._inflight += 1
                        self._tenant_inflight[tenant] += 1
                        self._class_inflight[prompt_class] += 1
                        self._w_t += float(weight)
                        return AcquireResult(ok=True, reason="admitted", waited_s=loop.time() - t0)
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
            finally:
                self._waiting -= 1

    async def release(self, weight: float, tenant: str = "default", prompt_class: str = "short") -> None:
        async with self._cond:
            self._inflight = max(0, self._inflight - 1)
            self._tenant_inflight[tenant] = max(0, self._tenant_inflight[tenant] - 1)
            self._class_inflight[prompt_class] = max(0, self._class_inflight[prompt_class] - 1)
            self._w_t = max(0.0, self._w_t - float(weight))
            self._cond.notify_all()
