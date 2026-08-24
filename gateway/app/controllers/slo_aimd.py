from __future__ import annotations

from app.controllers.base import Controller, Decision, decrease_c, increase_c
from app.window import Snapshot


class SloAimdController(Controller):
    name = "slo_aimd"

    def _pressure(self, snap: Snapshot) -> tuple[bool, bool]:
        settings = self.settings
        # Control on backend TTFT, not user-facing TTFT. Queue wait is demand,
        # not Bedrock saturation — decreasing on it traps C at 1 during bursts.
        backend_p95 = snap.backend_ttft_p95_ms
        ttft_bad = False
        if settings.use_ttft_signal and backend_p95 is not None:
            ttft_bad = backend_p95 > settings.ttft_slo_ms
        throttle_bad = False
        if settings.use_throttle_signal:
            throttle_bad = (
                snap.throttle_rate > settings.throttle_rate_low
                or snap.error_rate > settings.error_rate_low
                or snap.throttle_n > 0
            )
        ttft_good = True
        if settings.use_ttft_signal:
            ttft_good = backend_p95 is not None and backend_p95 < settings.ttft_slo_ms
        throttle_good = True
        if settings.use_throttle_signal:
            throttle_good = (
                snap.throttle_n == 0
                and snap.throttle_rate <= settings.throttle_rate_low
                and snap.error_rate <= settings.error_rate_low
            )
        return ttft_bad or throttle_bad, ttft_good and throttle_good

    def _demand_saturated(self, snap: Snapshot) -> bool:
        if snap.waiting > 0 or snap.max_waiting > 0:
            return True
        if snap.queue_p95_ms is not None and snap.queue_p95_ms >= self.settings.demand_queue_ms:
            return True
        return False

    def decide(self, snap: Snapshot) -> Decision:
        if snap.n < self.settings.min_samples:
            self.last_action = "hold"
            return Decision(c=snap.c, action="hold")
        bad, good = self._pressure(snap)
        if bad:
            nxt = decrease_c(snap.c, self.settings)
            self.last_action = "decrease"
            return Decision(c=nxt, action="decrease")
        if good:
            if self.settings.use_demand_gate and not self._demand_saturated(snap):
                self.last_action = "hold-demand"
                return Decision(c=snap.c, action="hold-demand")
            nxt = increase_c(snap.c, self.settings)
            self.last_action = "increase" if nxt > snap.c else "hold"
            return Decision(c=nxt, action=self.last_action)
        self.last_action = "hold"
        return Decision(c=snap.c, action="hold")
