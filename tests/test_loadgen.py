from loadgen.openloop import Phase, phase_at, pick_prompt_class


def test_phase_at():
    phases = [
        Phase(until_s=10, rps=1, prompt_class="short"),
        Phase(until_s=20, rps=2, prompt_class="long"),
    ]
    assert phase_at(phases, 0).prompt_class == "short"
    assert phase_at(phases, 10).prompt_class == "long"
    assert phase_at(phases, 99).rps == 2


def test_pick_prompt_class_mix_is_deterministic_with_seed():
    import random

    phase = Phase(until_s=1, mix={"short": 1.0, "long": 0.0})
    random.seed(0)
    assert pick_prompt_class(phase) == "short"
    phase_long = Phase(until_s=1, prompt_class="short", mix={"short": 0.0, "long": 1.0})
    assert pick_prompt_class(phase_long) == "long"


def test_closed_loop_streams_do_not_use_open_loop():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from loadgen.openloop import run

    with (
        patch("loadgen.openloop.run_closed_loop", new_callable=AsyncMock) as closed,
        patch("loadgen.openloop.run_open_loop", new_callable=AsyncMock) as opened,
    ):
        args = SimpleNamespace(
            url="http://127.0.0.1:8080",
            poisson=False,
            mode="closed_loop",
            concurrency=1,
            warmup_s=0,
            measure_s=1,
            streams=[[{"until_s": 1, "concurrency": 1, "prompt_class": "long", "tenant_id": "default"}]],
        )
        asyncio.run(run(args))
        closed.assert_awaited()
        opened.assert_not_called()
