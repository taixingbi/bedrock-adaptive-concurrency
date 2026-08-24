from app.config import Settings
from app.controllers.fixed import FixedController
from app.controllers.gradient import GradientController
from app.controllers.slo_aimd import SloAimdController
from app.controllers.token_slo_aimd import TokenSloAimdController
from app.window import Snapshot


def snap(**kwargs) -> Snapshot:
    base = dict(
        n=20,
        ttft_p95_ms=500.0,
        backend_ttft_p95_ms=500.0,
        throttle_n=0,
        error_n=0,
        throttle_rate=0.0,
        error_rate=0.0,
        slo_n=20,
        achieved_n=20,
        offered_n=20,
        input_tokens=1000,
        output_tokens=100,
        c=8,
        inflight=4,
        waiting=0,
        w_t=4 * (512 + 128),
        queue_p95_ms=1.0,
    )
    base.update(kwargs)
    return Snapshot(**base)


def test_fixed_holds():
    settings = Settings(policy="fixed", concurrency_limit=4)
    decision = FixedController(settings).decide(snap(c=99))
    assert decision.c == 4
    assert decision.action == "hold"


def test_slo_aimd_increases_when_healthy_and_saturated():
    settings = Settings(policy="slo_aimd", ttft_slo_ms=2000, concurrency_limit=8, c_max=64)
    decision = SloAimdController(settings).decide(snap(ttft_p95_ms=400, c=8, waiting=2, queue_p95_ms=20))
    assert decision.action == "increase"
    assert decision.c == 9


def test_slo_aimd_holds_when_healthy_but_unsaturated():
    settings = Settings(policy="slo_aimd", ttft_slo_ms=2000, concurrency_limit=8, c_max=64)
    decision = SloAimdController(settings).decide(snap(ttft_p95_ms=400, c=18, inflight=1, waiting=0, queue_p95_ms=0.0))
    assert decision.action == "hold-demand"
    assert decision.c == 18


def test_slo_aimd_decreases_on_backend_slo_violation():
    settings = Settings(policy="slo_aimd", ttft_slo_ms=2000, aimd_beta=0.7, c_min=1)
    decision = SloAimdController(settings).decide(snap(backend_ttft_p95_ms=4000, ttft_p95_ms=4000, c=10))
    assert decision.action == "decrease"
    assert decision.c == 7


def test_slo_aimd_increases_when_queue_inflates_user_ttft():
    settings = Settings(policy="slo_aimd", ttft_slo_ms=576, concurrency_limit=1, c_max=64)
    decision = SloAimdController(settings).decide(
        snap(ttft_p95_ms=2200, backend_ttft_p95_ms=300, c=1, waiting=5, queue_p95_ms=1800)
    )
    assert decision.action == "increase"
    assert decision.c == 2


def test_slo_aimd_does_not_decrease_on_queue_inflated_user_ttft():
    settings = Settings(policy="slo_aimd", ttft_slo_ms=576, c_min=1)
    decision = SloAimdController(settings).decide(
        snap(ttft_p95_ms=2200, backend_ttft_p95_ms=300, c=1, waiting=0, queue_p95_ms=0.0)
    )
    assert decision.action == "hold-demand"
    assert decision.c == 1


def test_slo_aimd_decreases_on_throttle():
    settings = Settings(policy="slo_aimd", ttft_slo_ms=2000, aimd_beta=0.7)
    decision = SloAimdController(settings).decide(snap(ttft_p95_ms=400, throttle_n=2, throttle_rate=0.1, c=10))
    assert decision.action == "decrease"


def test_slo_aimd_holds_without_samples():
    settings = Settings(policy="slo_aimd", min_samples=5)
    decision = SloAimdController(settings).decide(snap(n=1, c=8))
    assert decision.action == "hold"
    assert decision.c == 8


def test_slo_aimd_holds_without_backend_ttft():
    settings = Settings(policy="slo_aimd", ttft_slo_ms=576)
    decision = SloAimdController(settings).decide(
        snap(backend_ttft_p95_ms=None, ttft_p95_ms=2200, c=1, waiting=4, queue_p95_ms=100)
    )
    assert decision.action == "hold"
    assert decision.c == 1


def test_ablation_without_ttft_ignores_latency():
    settings = Settings(policy="slo_aimd", use_ttft_signal=False, ttft_slo_ms=100, use_throttle_signal=True)
    decision = SloAimdController(settings).decide(snap(ttft_p95_ms=5000, throttle_n=0, c=8, waiting=1, queue_p95_ms=20))
    assert decision.action == "increase"


def test_ablation_additive_decrease():
    settings = Settings(use_multiplicative_decrease=False, ttft_slo_ms=100)
    decision = SloAimdController(settings).decide(snap(backend_ttft_p95_ms=5000, ttft_p95_ms=5000, c=10))
    assert decision.c == 9


def test_token_aware_decreases_when_w_t_high():
    settings = Settings(policy="token_slo_aimd", ttft_slo_ms=2000, token_pressure_gamma=1.2)
    heavy = snap(ttft_p95_ms=400, c=8, w_t=8 * (512 + 128) * 3)
    decision = TokenSloAimdController(settings).decide(heavy)
    assert decision.action == "decrease-token"
    assert decision.c < 8


def test_token_aware_hold_instead_of_increase():
    settings = Settings(policy="token_slo_aimd", ttft_slo_ms=2000, token_pressure_gamma=1.2)
    mild = snap(ttft_p95_ms=400, c=8, w_t=8 * (512 + 128) * 1.1, waiting=1, queue_p95_ms=20)
    decision = TokenSloAimdController(settings).decide(mild)
    assert decision.action == "hold-token"
    assert decision.c == 8


def test_token_ablation_disables_w_t():
    settings = Settings(policy="token_slo_aimd", use_token_awareness=False, ttft_slo_ms=2000)
    heavy = snap(ttft_p95_ms=400, c=8, w_t=8 * (512 + 128) * 3, waiting=1, queue_p95_ms=20)
    decision = TokenSloAimdController(settings).decide(heavy)
    assert decision.action == "increase"


def test_gradient_decreases_when_ttft_rises():
    settings = Settings(policy="gradient", gradient_epsilon=0.05)
    ctrl = GradientController(settings)
    first = ctrl.decide(snap(ttft_p95_ms=400, c=8))
    assert first.action == "hold"
    second = ctrl.decide(snap(ttft_p95_ms=800, c=8))
    assert second.action == "decrease"
