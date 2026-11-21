"""Structured estimated token-pressure breakdown helpers for runtime observability."""

from __future__ import annotations

import json
from typing import Any

from ...core.context.engine_limits import APPROX_CHARS_PER_TOKEN

_TOKEN_BUCKETS = ("system", "history", "tool", "current_user")


def _estimate_value_tokens(value: Any, *, approx_chars_per_token: int) -> int:
    ratio = max(1, int(approx_chars_per_token or APPROX_CHARS_PER_TOKEN or 4))
    try:
        char_count = len(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        char_count = len(str(value))
    return max(1, char_count // ratio)


def _last_user_message_signature(messages: list[dict[str, Any]]) -> tuple[str, str] | None:
    for message in reversed(messages):
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        return (
            str(message.get("content") or "").strip(),
            str(message.get("name") or "").strip(),
        )
    return None


def _message_bucket(message: dict[str, Any], *, current_user_signature: tuple[str, str] | None) -> str:
    role = str(message.get("role") or "").strip().lower()
    if role == "system":
        return "system"
    if role == "tool" or list(message.get("tool_calls") or []):
        return "tool"
    if role == "user" and current_user_signature is not None:
        signature = (
            str(message.get("content") or "").strip(),
            str(message.get("name") or "").strip(),
        )
        if signature == current_user_signature:
            return "current_user"
    return "history"


def _build_breakdown_stage(
    messages: list[dict[str, Any]],
    *,
    approx_chars_per_token: int,
    current_user_signature: tuple[str, str] | None,
) -> dict[str, Any]:
    contributions = {
        bucket: {
            "message_count": 0,
            "estimated_tokens": 0,
        }
        for bucket in _TOKEN_BUCKETS
    }
    total_estimated_tokens = 0

    for message in messages:
        bucket = _message_bucket(message, current_user_signature=current_user_signature)
        estimated_tokens = _estimate_value_tokens(message, approx_chars_per_token=approx_chars_per_token)
        contributions[bucket]["message_count"] += 1
        contributions[bucket]["estimated_tokens"] += estimated_tokens
        total_estimated_tokens += estimated_tokens

    for bucket in _TOKEN_BUCKETS:
        estimated_tokens = contributions[bucket]["estimated_tokens"]
        contributions[bucket]["share_of_total"] = (
            round(estimated_tokens / total_estimated_tokens, 4) if total_estimated_tokens > 0 else 0.0
        )

    return {
        "message_count": len(messages),
        "estimated_total_tokens": total_estimated_tokens,
        "contributions": contributions,
    }


def build_token_pressure_observability_payload(
    before_messages: list[dict[str, Any]],
    after_messages: list[dict[str, Any]],
    *,
    approx_chars_per_token: int = APPROX_CHARS_PER_TOKEN,
    compaction_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an estimated token-pressure breakdown for trace and logging payloads.

    The payload is intentionally diagnostic only. It explains where prompt pressure comes
    from before and after compaction without implying provider-billed usage.
    """

    ratio = max(1, int(approx_chars_per_token or APPROX_CHARS_PER_TOKEN or 4))
    current_user_signature = _last_user_message_signature(before_messages)
    if current_user_signature is None:
        current_user_signature = _last_user_message_signature(after_messages)

    before = _build_breakdown_stage(
        before_messages,
        approx_chars_per_token=ratio,
        current_user_signature=current_user_signature,
    )
    after = _build_breakdown_stage(
        after_messages,
        approx_chars_per_token=ratio,
        current_user_signature=current_user_signature,
    )

    estimated_tokens_before = before["estimated_total_tokens"]
    estimated_tokens_after = after["estimated_total_tokens"]
    estimated_tokens_reduced = max(0, estimated_tokens_before - estimated_tokens_after)
    message_count_before = before["message_count"]
    message_count_after = after["message_count"]

    compaction_summary = {
        "message_count_before": message_count_before,
        "message_count_after": message_count_after,
        "messages_removed": max(0, message_count_before - message_count_after),
        "estimated_tokens_before": estimated_tokens_before,
        "estimated_tokens_after": estimated_tokens_after,
        "estimated_tokens_reduced": estimated_tokens_reduced,
    }
    for key, value in (compaction_stats or {}).items():
        if key in compaction_summary:
            continue
        compaction_summary[key] = value

    return {
        "kind": "token_pressure_breakdown",
        "estimation": {
            "approx_chars_per_token": ratio,
            "estimated_only": True,
            "not_for_billing": True,
        },
        "before_compaction": before,
        "after_compaction": after,
        "compaction": compaction_summary,
    }


__all__ = ["build_token_pressure_observability_payload"]
