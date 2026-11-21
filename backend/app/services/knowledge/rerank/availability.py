"""After the reranker fails, searches skip it for a while.

A reranker that is down would otherwise cost every search, and every Workspace in a search's scope, its full
timeout. After one unavailable answer the reranker is skipped for ``SUSPEND_SECONDS``; a skipped search reports
``rerank: unavailable`` exactly like a failed one, so the state stays visible and nothing degrades silently. The
window is per process and per reranker key; the next search after it tries the reranker again.
"""

from __future__ import annotations

import time

SUSPEND_SECONDS = 60.0

_suspended_until: dict[str, float] = {}


def _now() -> float:
    return time.monotonic()


def rerank_suspended(reranker_key: str) -> bool:
    """Whether the reranker failed less than ``SUSPEND_SECONDS`` ago."""
    until = _suspended_until.get(reranker_key)
    return until is not None and _now() < until


def record_rerank_unavailable(reranker_key: str) -> None:
    _suspended_until[reranker_key] = _now() + SUSPEND_SECONDS


def record_rerank_ok(reranker_key: str) -> None:
    _suspended_until.pop(reranker_key, None)


def reset_rerank_availability() -> None:
    """Forget every suspension (tests)."""
    _suspended_until.clear()


__all__ = [
    "SUSPEND_SECONDS",
    "record_rerank_ok",
    "record_rerank_unavailable",
    "rerank_suspended",
    "reset_rerank_availability",
]
