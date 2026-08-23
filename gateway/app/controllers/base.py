from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.window import Snapshot


def clamp_c(value: float, settings: Settings) -> int:
    return max(settings.c_min, min(settings.c_max, int(value)))


def decrease_c(c: int, settings: Settings) -> int:
    if settings.use_multiplicative_decrease:
        return clamp_c(max(settings.c_min, int(c * settings.aimd_beta)), settings)
    return clamp_c(c - 1, settings)


def increase_c(c: int, settings: Settings) -> int:
    return clamp_c(c + 1, settings)


@dataclass
class Decision:
    c: int
    action: str


class Controller:
    name = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last_action = "init"

    @property
    def retry_on_throttle(self) -> bool:
        return False

    def decide(self, snap: Snapshot) -> Decision:
        raise NotImplementedError
