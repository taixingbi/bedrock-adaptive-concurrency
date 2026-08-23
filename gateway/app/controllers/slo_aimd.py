from __future__ import annotations

from app.controllers.base import Controller, Decision, decrease_c, increase_c
from app.window import Snapshot


class SloAimdController(Controller):
    name = "slo_aimd"

    def _pressure(self, snap: Snapshot) -> tuple[bool, bool]:
        settings = self.settings
        ttft_bad = False
        if settings.use_ttft_signal and snap.ttft_p95_ms is not None:
            ttft_bad = snap.ttft_p95_ms > settings.ttft_slo_ms
        throttle_bad = False
        if settings.use_throttle_signal:
            throttle_bad = (
                snap.throttle_rate > settings.throttle_rate_low
                or snap.error_rate > settings.error_rate_low
                or snap.throttle_n > 0
            )
        ttft_good = True
        if settings.use_ttft_signal:
            ttft_good = snap.ttft_p95_ms is not None and snap.ttft_p95_ms < settings.ttft_slo_ms
        throttle_good = True
        if settings.use_throttle_signal:
            throttle_good = (
                snap.throttle_n == 0
                and snap.throttle_rate <= settings.throttle_rate_low
                and snap.error_rate <= settings.error_rate_low
            )
        return ttft_bad or throttle_bad, ttft_good and throttle_good

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
            nxt = increase_c(snap.c, self.settings)
            self.last_action = "increase" if nxt > snap.c else "hold"
            return Decision(c=nxt, action=self.last_action)
        self.last_action = "hold"
        return Decision(c=snap.c, action="hold")
