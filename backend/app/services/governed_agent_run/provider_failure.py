"""The safe cause of a failed model request, from the runtime chain's typed attempt facts.

A ``provider_error`` (or an exhausted policy) would otherwise end a run with no cause at all. This module reads only
the closed facts of the chain's attempts — the alias, the runtime error class and the provider's own
``safe_detail`` (already sanitized by the provider, e.g. ``litellm/upstream_detail.py``) — never ``str(exc)``
or the attempt's free ``error`` text. The result is sanitized once more and bounded, so it can be logged
and stored for the UI.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..model_gateway.litellm.upstream_detail import sanitize_detail

MAX_FAILURE_DETAIL_CHARS = 300


def failure_detail(attempts: Sequence[Any] | None) -> str:
    """``"<alias>: <error class>: <safe detail>"`` of the last failed attempt, or ``""``."""
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
