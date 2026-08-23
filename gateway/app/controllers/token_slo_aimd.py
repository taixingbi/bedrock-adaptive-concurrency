from __future__ import annotations

from app.controllers.base import Decision, decrease_c
from app.controllers.slo_aimd import SloAimdController
from app.window import Snapshot


class TokenSloAimdController(SloAimdController):
    """SLO-AIMD plus inflight token pressure W_t. Does not use quota %."""

    name = "token_slo_aimd"

    def decide(self, snap: Snapshot) -> Decision:
        base = super().decide(snap)
        if not self.settings.use_token_awareness:
            return base
        if snap.n < self.settings.min_samples:
            return base
        w_ref = max(snap.c * self.settings.w_short, 1.0)
        ratio = snap.w_t / w_ref
        if ratio > self.settings.token_pressure_gamma:
            nxt = decrease_c(snap.c, self.settings)
            self.last_action = "decrease-token"
            return Decision(c=nxt, action="decrease-token")
        if ratio > 1.0 and base.action == "increase":
            self.last_action = "hold-token"
            return Decision(c=snap.c, action="hold-token")
        return base
