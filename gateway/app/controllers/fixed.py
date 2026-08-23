from __future__ import annotations

from app.controllers.base import Controller, Decision
from app.window import Snapshot


class FixedController(Controller):
    name = "fixed"

    def decide(self, snap: Snapshot) -> Decision:
        self.last_action = "hold"
        return Decision(c=self.settings.concurrency_limit, action="hold")
