from __future__ import annotations

from app.config import Settings
from app.controllers.base import Controller
from app.controllers.fixed import FixedController
from app.controllers.gradient import GradientController
from app.controllers.retry_backoff import RetryBackoffController
from app.controllers.slo_aimd import SloAimdController
from app.controllers.token_slo_aimd import TokenSloAimdController


def build_controller(settings: Settings) -> Controller:
    name = settings.policy.strip().lower().replace("-", "_")
    if name in {"fixed", "fixed_low", "fixed_knee", "fixed_high"}:
        return FixedController(settings)
    if name in {"retry", "retry_backoff"}:
        return RetryBackoffController(settings)
    if name in {"gradient", "generic_gradient"}:
        return GradientController(settings)
    if name in {"slo_aimd", "slo-aimd"}:
        return SloAimdController(settings)
    if name in {"token_slo_aimd", "token_aware", "full"}:
        return TokenSloAimdController(settings)
    raise ValueError(f"unknown policy: {settings.policy}")
