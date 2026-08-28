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


def test_class_only_cannot_isolate_same_class_tenants():
    """E5 negative control: both tenants short, global class pool cannot see A vs B."""

    async def _run():
        limiter = ConcurrencyLimiter(
            limit=2,
            queue_max=0,
            class_caps={"short": 2},
            use_class_cap=True,
        )
        b1 = await limiter.acquire(1, tenant="B", prompt_class="short")
        b2 = await limiter.acquire(1, tenant="B", prompt_class="short")
        assert b1.ok and b2.ok
        a = await limiter.acquire(1, tenant="A", prompt_class="short")
        assert not a.ok
        assert a.reason in {"class_full", "queue_full"}
        await limiter.release(1, tenant="B", prompt_class="short")
        await limiter.release(1, tenant="B", prompt_class="short")

    asyncio.run(_run())


def test_tenant_cap_protects_interactive_from_noisy_neighbor():
    async def _run():
        limiter = ConcurrencyLimiter(
            limit=2,
            queue_max=0,
            tenant_caps={"A": 2, "B": 1},
            use_tenant_cap=True,
        )
        b1 = await limiter.acquire(1, tenant="B", prompt_class="short")
        b2 = await limiter.acquire(1, tenant="B", prompt_class="short")
        assert b1.ok
        assert not b2.ok
        assert b2.reason == "tenant_full"
        a = await limiter.acquire(1, tenant="A", prompt_class="short")
        assert a.ok
        await limiter.release(1, tenant="B", prompt_class="short")
        await limiter.release(1, tenant="A", prompt_class="short")

    asyncio.run(_run())


def test_hierarchical_caps_pair_not_global_class():
    """A long must not consume B's class budget; inflight is (tenant, class)."""

    async def _run():
        limiter = ConcurrencyLimiter(
            limit=2,
            queue_max=0,
            tenant_caps={"A": 2, "B": 1},
            tenant_class_caps={"A": {"short": 2, "long": 1}, "B": {"short": 1, "long": 1}},
            use_tenant_cap=True,
            use_tenant_class_cap=True,
        )
        a_long = await limiter.acquire(1, tenant="A", prompt_class="long")
        a_long2 = await limiter.acquire(1, tenant="A", prompt_class="long")
        assert a_long.ok
        assert not a_long2.ok
        assert a_long2.reason == "tenant_class_full"
        a_short = await limiter.acquire(1, tenant="A", prompt_class="short")
        b_short = await limiter.acquire(1, tenant="B", prompt_class="short")
        assert a_short.ok
        assert not b_short.ok  # global C=2 already full (A long + A short)
        await limiter.release(1, tenant="A", prompt_class="long")
        b_short = await limiter.acquire(1, tenant="B", prompt_class="short")
        assert b_short.ok
        await limiter.release(1, tenant="A", prompt_class="short")
        await limiter.release(1, tenant="B", prompt_class="short")

    asyncio.run(_run())


def test_overflow_reject_unifies_global_and_cap_full():
    async def _run():
        queued = ConcurrencyLimiter(limit=1, queue_max=4)
        await queued.acquire(1)
        waiter = asyncio.create_task(queued.acquire(1, timeout_s=0.2))
        await asyncio.sleep(0.05)
        assert not waiter.done()
        waiter.cancel()
        try:
            await waiter
        except asyncio.CancelledError:
            pass
        await queued.release(1)

        limiter = ConcurrencyLimiter(limit=1, queue_max=4, overflow_mode="reject")
        first = await limiter.acquire(1)
        assert first.ok
        extra = await limiter.acquire(1)
        assert not extra.ok
        assert extra.reason == "global_full"
        assert extra.waited_s == 0.0
        assert limiter.waiting == 0
        await limiter.release(1)

        tenants = ConcurrencyLimiter(
            limit=2,
            queue_max=4,
            tenant_caps={"A": 1, "B": 1},
            use_tenant_cap=True,
            overflow_mode="reject",
        )
        b = await tenants.acquire(1, tenant="B")
        assert b.ok
        extra_b = await tenants.acquire(1, tenant="B")
        assert extra_b.reason == "tenant_full"
        a = await tenants.acquire(1, tenant="A")
        assert a.ok
        await tenants.release(1, tenant="B")
        await tenants.release(1, tenant="A")

    asyncio.run(_run())
