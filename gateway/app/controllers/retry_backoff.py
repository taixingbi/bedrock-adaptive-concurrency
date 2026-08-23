from __future__ import annotations

from app.controllers.base import Controller, Decision
from app.window import Snapshot


class RetryBackoffController(Controller):
    """High static C; retries happen in the request path, not by adapting C."""

    name = "retry_backoff"

    @property
    def retry_on_throttle(self) -> bool:
        return True

    def decide(self, snap: Snapshot) -> Decision:
        self.last_action = "hold"
        return Decision(c=self.settings.concurrency_limit, action="hold")
