"""The safe cause of a failed model request, from the runtime chain's typed attempt facts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..model_gateway.litellm.upstream_detail import sanitize_detail

MAX_FAILURE_DETAIL_CHARS = 300


def failure_detail(attempts: Sequence[Any] | None) -> str:
    failed_attempts = [attempt for attempt in attempts or () if isinstance(attempt, dict)
                       and attempt.get("status") == "error"]
    if not failed_attempts:
        return ""
    last = failed_attempts[-1]
    parts = [str(last.get(key) or "") for key in ("model", "error_class")]
    detail = last.get("safe_detail")
    if isinstance(detail, str) and detail:
        parts.append(detail)
    return sanitize_detail(": ".join(part for part in parts if part), max_chars=MAX_FAILURE_DETAIL_CHARS)


__all__ = ["MAX_FAILURE_DETAIL_CHARS", "failure_detail"]
