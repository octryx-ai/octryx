"""Aggregates derived from turn trace usage payloads."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import TurnTrace


async def load_trace_usage_stats(db: AsyncSession, *, session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "request_count": 0,
            "cache_read_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "non_cached_input_tokens": 0,
        }

    usage_rows = (
        await db.execute(select(TurnTrace.usage_json).where(TurnTrace.session_id.in_(session_ids)))
    ).scalars()
    cache_read_tokens = 0
    cache_write_tokens = 0
    non_cached_input_tokens = 0
    input_tokens = 0
    output_tokens = 0
    request_count = 0
    for usage in usage_rows:
        payload = usage if isinstance(usage, dict) else {}
        if payload:
            request_count += 1
        input_tokens += _usage_int(
            payload.get("prompt_tokens"),
            payload.get("input_tokens"),
            payload.get("inputTokens"),
        )
        output_tokens += _usage_int(
            payload.get("completion_tokens"),
            payload.get("output_tokens"),
            payload.get("outputTokens"),
        )
        cache_read_tokens += _usage_int(
            payload.get("bedrock_cache_read_input_tokens"),
            payload.get("cacheReadInputTokens"),
        )
        cache_write_tokens += _usage_int(
            payload.get("bedrock_cache_write_input_tokens"),
            payload.get("cacheWriteInputTokens"),
        )
        non_cached_input_tokens += _usage_int(
            payload.get("bedrock_input_tokens_non_cached"),
            payload.get("inputTokens"),
        )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "request_count": request_count,
        "cache_read_input_tokens": cache_read_tokens,
        "cache_write_input_tokens": cache_write_tokens,
        "non_cached_input_tokens": non_cached_input_tokens,
    }


def _usage_int(*values: Any) -> int:
    for value in values:
        try:
            number = int(value or 0)
        except (TypeError, ValueError):
            continue
        if number:
            return number
    return 0
