"""When the pet asks the platform again (adaptive polling).

- after an answer: the server's ``poll_after_seconds`` (kept within 5 s … 15 min), else a default per state
  (sooner while something works or waits for the person);
- after a failure (unreachable, 5xx): exponential backoff 15 s → 5 min with jitter ×0.5–1.5, reset by an answer;
- signed out or refused for good (401/403): every 5 minutes, so a new login is picked up without a restart;
- "Refresh now" from the menu wakes the loop at once (``runner``).
"""

from __future__ import annotations

import random
from collections.abc import Callable

MIN_SECONDS = 5
MAX_SECONDS = 15 * 60
DEFAULT_SECONDS = {"needs_you": 15, "problem": 15, "working": 30, "done": 60, "resting": 60}
FALLBACK_SECONDS = 60
BACKOFF_FIRST = 15.0
BACKOFF_MAX = 300.0
SIGNED_OUT_SECONDS = 300.0


def _clamp(seconds: float) -> float:
    return float(min(MAX_SECONDS, max(MIN_SECONDS, seconds)))


class Schedule:
    def __init__(self, *, rand: Callable[[], float] = random.random) -> None:
        self._rand = rand
        self.failures = 0

    def after_answer(self, state: str, hint: int | None) -> float:
        self.failures = 0
        return _clamp(hint if hint else DEFAULT_SECONDS.get(state, FALLBACK_SECONDS))

    def after_failure(self) -> float:
        self.failures += 1
        base = min(BACKOFF_MAX, BACKOFF_FIRST * 2 ** (self.failures - 1))
        return _clamp(base * (0.5 + self._rand()))

    def after_signed_out(self) -> float:
        self.failures = 0
        return SIGNED_OUT_SECONDS


__all__ = ["DEFAULT_SECONDS", "Schedule"]
