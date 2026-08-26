import asyncio

from app.limiter import ConcurrencyLimiter


def test_acquire_and_release():
    async def _run():
        limiter = ConcurrencyLimiter(limit=1, queue_max=4)
        first = await limiter.acquire(10)
        assert first.ok
        assert limiter.inflight == 1
        assert limiter.w_t == 10
        await limiter.release(10)
        assert limiter.inflight == 0
        assert limiter.w_t == 0

    asyncio.run(_run())


def test_queue_full_rejects_when_saturated():
    async def _run():
        limiter = ConcurrencyLimiter(limit=1, queue_max=0)
        first = await limiter.acquire(1)
        assert first.ok
        second = await limiter.acquire(1)
        assert not second.ok
        assert second.reason == "queue_full"
        await limiter.release(1)

    asyncio.run(_run())


def test_set_limit_wakes_waiter():
    async def _run():
        limiter = ConcurrencyLimiter(limit=1, queue_max=4)
        await limiter.acquire(1)

        async def waiter():
            return await limiter.acquire(1)

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        await limiter.set_limit(2)
        result = await asyncio.wait_for(task, timeout=1)
        assert result.ok
        assert limiter.inflight == 2
        await limiter.release(1)
        await limiter.release(1)

    asyncio.run(_run())


def test_queue_timeout():
    async def _run():
        limiter = ConcurrencyLimiter(limit=1, queue_max=4)
        await limiter.acquire(1)
        timed_out = await limiter.acquire(1, timeout_s=0.05)
        assert not timed_out.ok
        assert timed_out.reason == "queue_timeout"
        assert limiter.waiting == 0
        await limiter.release(1)

    asyncio.run(_run())


def test_tenant_cap_rejects_without_blocking_other_tenant():
    async def _run():
        limiter = ConcurrencyLimiter(
            limit=2,
            queue_max=4,
            tenant_caps={"A": 1, "B": 1},
            use_tenant_cap=True,
        )
        a = await limiter.acquire(1, tenant="A")
        b = await limiter.acquire(1, tenant="B")
        assert a.ok and b.ok
        extra_a = await limiter.acquire(1, tenant="A")
        assert not extra_a.ok
        assert extra_a.reason == "tenant_full"
        await limiter.release(1, tenant="A")
        again = await limiter.acquire(1, tenant="A")
        assert again.ok
        await limiter.release(1, tenant="A")
        await limiter.release(1, tenant="B")

    asyncio.run(_run())


def test_class_cap_rejects_long_but_admits_short():
    async def _run():
        limiter = ConcurrencyLimiter(
            limit=2,
            queue_max=4,
            class_caps={"short": 2, "long": 1},
            use_class_cap=True,
        )
        long1 = await limiter.acquire(1, prompt_class="long")
        long2 = await limiter.acquire(1, prompt_class="long")
        assert long1.ok
        assert not long2.ok
        assert long2.reason == "class_full"
        short = await limiter.acquire(1, prompt_class="short")
        assert short.ok
        await limiter.release(1, prompt_class="long")
        await limiter.release(1, prompt_class="short")

    asyncio.run(_run())
