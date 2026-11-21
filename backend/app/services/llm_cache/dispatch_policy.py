"""Which model dispatches may read or write the LLM response cache.

A Chat turn always reaches the model. A
cached answer is a different execution fact than a model decision, and the
cache key spans sessions, so a Chat turn neither reads nor writes the cache.
The cache stays available to non-interactive ``run_agent`` callers, which pass
no ``run_origin``, and only for plain completions: a dispatch that offers tools
or carries tool results is never cached.
"""

from __future__ import annotations

from typing import Any

from ...models.runtime.product_run import RUN_ORIGIN_CHAT_TURN

RESPONSE_CACHE_EXCLUDED_ORIGINS: frozenset[str] = frozenset({RUN_ORIGIN_CHAT_TURN})


def response_cache_allowed(*, run_origin: str | None, tools: list[dict] | None, messages: list[Any]) -> bool:
    """Return whether this dispatch may use the response cache."""
    if run_origin in RESPONSE_CACHE_EXCLUDED_ORIGINS:
        return False
    if tools:
        return False
    return not any(
        str(message.get("role") or "").strip() == "tool" for message in messages if isinstance(message, dict)
    )


__all__ = ["RESPONSE_CACHE_EXCLUDED_ORIGINS", "response_cache_allowed"]
