"""How long each stage of a Knowledge search took."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

STAGES = ("lexical", "embed", "vector_query", "vector", "resolve", "rerank")


class StageTimer:
    def __init__(self) -> None:
        self._started = time.perf_counter()
        self._stages: dict[str, float] = {}
        self.total_ms: float | None = None

    def add(self, name: str, milliseconds: float) -> None:
        self._stages[name] = self._stages.get(name, 0.0) + milliseconds

    def finish(self) -> None:
        self.total_ms = (time.perf_counter() - self._started) * 1000.0

    def as_dict(self) -> dict[str, int]:
        values = {name: round(value) for name, value in self._stages.items()}
        if self.total_ms is not None:
            values["total"] = round(self.total_ms)
        return values


_open: ContextVar[tuple[StageTimer, ...]] = ContextVar("knowledge_search_stage_timers", default=())


@contextmanager
def measuring() -> Iterator[StageTimer]:
    timer = StageTimer()
    token = _open.set((*_open.get(), timer))
    try:
        yield timer
    finally:
        _open.reset(token)
        timer.finish()


@contextmanager
def timed_stage(name: str) -> Iterator[None]:
    timers = _open.get()
    if not timers:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - started) * 1000.0
        for timer in timers:
            timer.add(name, elapsed)


__all__ = ["STAGES", "StageTimer", "measuring", "timed_stage"]
