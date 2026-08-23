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
