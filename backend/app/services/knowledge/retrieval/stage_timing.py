"""How long each stage of a Knowledge search took.

A search runs lexical retrieval, query embedding, vector retrieval, citation resolution and the reranker, one
after another and once per Workspace in scope. Without numbers per stage a slow search cannot be explained. A
``measuring()`` block collects milliseconds per stage name; ``timed_stage(name)`` adds the time of its block to
every measurement that is open, so a stage deep in the stack (the query embedding inside the query store) is
measured without passing a timer through every signature. Stages can nest (``embed`` and ``vector_query``, the
index query alone, lie inside ``vector``), so
the stage times do not add up to the total.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

STAGES = ("lexical", "embed", "vector_query", "vector", "resolve", "rerank")


class StageTimer:
    """Milliseconds per stage name, plus the wall time of the whole measurement."""

    def __init__(self) -> None:
        self._started = time.perf_counter()
        self._stages: dict[str, float] = {}
        self.total_ms: float | None = None

    def add(self, name: str, milliseconds: float) -> None:
        self._stages[name] = self._stages.get(name, 0.0) + milliseconds

    def finish(self) -> None:
        self.total_ms = (time.perf_counter() - self._started) * 1000.0

    def as_dict(self) -> dict[str, int]:
        """``{stage: ms}`` rounded to whole milliseconds, ``total`` included once finished."""
        values = {name: round(value) for name, value in self._stages.items()}
        if self.total_ms is not None:
            values["total"] = round(self.total_ms)
        return values


_open: ContextVar[tuple[StageTimer, ...]] = ContextVar("knowledge_search_stage_timers", default=())


@contextmanager
def measuring() -> Iterator[StageTimer]:
    """Collect stage times of everything awaited inside the block (outer measurements keep collecting too)."""
    timer = StageTimer()
    token = _open.set((*_open.get(), timer))
    try:
        yield timer
    finally:
        _open.reset(token)
        timer.finish()


@contextmanager
def timed_stage(name: str) -> Iterator[None]:
    """Add the duration of the block to every open measurement; free when nothing is measured."""
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
