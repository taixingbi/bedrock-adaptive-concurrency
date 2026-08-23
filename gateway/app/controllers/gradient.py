from __future__ import annotations

from app.controllers.base import Controller, Decision, decrease_c, increase_c
from app.window import Snapshot


class GradientController(Controller):
    """Request-count adaptive concurrency using TTFT P95 trend, not an SLO."""

    name = "gradient"

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._prev_p95: float | None = None

    def decide(self, snap: Snapshot) -> Decision:
        if snap.n < self.settings.min_samples or snap.ttft_p95_ms is None:
            self.last_action = "hold"
            return Decision(c=snap.c, action="hold")
        prev = self._prev_p95
        self._prev_p95 = snap.ttft_p95_ms
        if prev is None:
            self.last_action = "hold"
            return Decision(c=snap.c, action="hold")
        worse = snap.ttft_p95_ms > prev * (1.0 + self.settings.gradient_epsilon)
        if worse:
            nxt = decrease_c(snap.c, self.settings)
            self.last_action = "decrease"
            return Decision(c=nxt, action="decrease")
        nxt = increase_c(snap.c, self.settings)
        self.last_action = "increase" if nxt > snap.c else "hold"
        return Decision(c=nxt, action=self.last_action)
