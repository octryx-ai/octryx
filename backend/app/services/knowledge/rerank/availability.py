"""After the reranker fails, searches skip it for a while. A skipped search reports ``rerank: unavailable`` like a
failed one."""

from __future__ import annotations

import time

SUSPEND_SECONDS = 60.0

_suspended_until: dict[str, float] = {}


def _now() -> float:
    return time.monotonic()


def rerank_suspended(reranker_key: str) -> bool:
    until = _suspended_until.get(reranker_key)
    return until is not None and _now() < until


def record_rerank_unavailable(reranker_key: str) -> None:
    _suspended_until[reranker_key] = _now() + SUSPEND_SECONDS


def record_rerank_ok(reranker_key: str) -> None:
    _suspended_until.pop(reranker_key, None)


def reset_rerank_availability() -> None:
    _suspended_until.clear()


__all__ = [
    "SUSPEND_SECONDS",
    "record_rerank_ok",
    "record_rerank_unavailable",
    "rerank_suspended",
    "reset_rerank_availability",
]
