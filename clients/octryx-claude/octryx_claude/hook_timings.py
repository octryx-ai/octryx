"""Where a hook process's time goes: one line per hook in the launcher's ``logs/hook-timings.jsonl``.

Each step's seconds since the process started name the step. The ``exit`` mark comes from ``atexit``: when Claude Code's
own duration is far above it, the time went after the hook's code (a child or thread holding the process).
Local only, and no content: step names and seconds.
"""

from __future__ import annotations

import atexit
import json
import time
from collections.abc import Callable
from pathlib import Path

FILE_NAME = "hook-timings.jsonl"
MAX_BYTES = 1_000_000  # then the file moves to ``.1`` and a new one starts
STARTED = time.monotonic()  # imported first by ``entry``: the process's start, before the CLI's imports


class HookTimer:
    def __init__(self, event: str, *, started: float = STARTED, clock: Callable[[], float] = time.monotonic) -> None:
        self.event = event
        self._clock = clock
        self._started = started
        self.steps: dict[str, float] = {}
        self.facts: dict[str, str] = {}

    def mark(self, step: str) -> None:
        self.steps[step] = round(self._clock() - self._started, 3)

    def line(self) -> dict[str, object]:
        return {"event": self.event, "at": round(time.time(), 3), "steps": self.steps, **self.facts}

    def write(self, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / FILE_NAME
            if path.exists() and path.stat().st_size > MAX_BYTES:
                path.replace(folder / f"{FILE_NAME}.1")
            with path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(self.line()) + "\n")
        except OSError:
            pass  # timings never cost a hook


_current: HookTimer | None = None


def start(event: str, folder: Callable[[], Path]) -> HookTimer:
    """The process's timer; written at exit into ``folder()`` (resolved then, after the launcher's state is known)."""
    global _current
    timer = _current = HookTimer(event)

    def finish() -> None:
        timer.mark("exit")
        try:
            timer.write(folder())
        except Exception:  # noqa: BLE001 - timings never cost a hook
            pass

    atexit.register(finish)
    return timer


def start_for(argv: list[str]) -> None:
    """A hook command (``hook <event>``) times itself; both entry points call this first."""
    if argv[:1] == ["hook"] and len(argv) >= 2 and _current is None:
        start(argv[1], _log_folder)


def _log_folder() -> Path:
    from .state import default_root  # noqa: PLC0415 - needs fcntl; resolved at the hook's exit only

    return default_root() / "logs"


def mark(step: str, **facts: str) -> None:
    """A step of the running hook; nothing outside a hook process."""
    if _current is not None:
        _current.mark(step)
        _current.facts.update({key: str(value)[:80] for key, value in facts.items()})


__all__ = ["FILE_NAME", "HookTimer", "mark", "start", "start_for"]
