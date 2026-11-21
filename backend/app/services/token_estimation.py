from __future__ import annotations

import json
import math
import re
from typing import Any

_DENSE_SYMBOL_CHARS = frozenset('{}[]():,`"\\/_<>|@#%$^&*+=~-')
_LONG_FRAGMENT_PATTERN = re.compile(r"[A-Za-z0-9_./:-]{12,}")
_KNOWN_MODEL_FAMILY_HINTS: tuple[tuple[str, float], ...] = (
    ("gpt", 0.92),
    ("o1", 0.90),
    ("o3", 0.90),
    ("o4", 0.90),
    ("claude", 0.95),
    ("gemini", 0.95),
    ("llama", 0.95),
    ("qwen", 0.95),
    ("deepseek", 0.95),
    ("mistral", 0.95),
)


def _serialize_value(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _resolve_ratio(
    *,
    approx_chars_per_token: int,
    provider_name: str | None = None,
    model_id: str | None = None,
) -> float:
    ratio = max(1, int(approx_chars_per_token or 4))
    family_hint = " ".join(part for part in (provider_name, model_id) if part).lower()
    for hint, multiplier in _KNOWN_MODEL_FAMILY_HINTS:
        if hint in family_hint:
            return max(1.0, ratio * multiplier)
    return float(ratio)


def _estimate_text_pressure_tokens(text: str) -> int:
    if not text:
        return 0
    dense_symbol_count = sum(1 for char in text if char in _DENSE_SYMBOL_CHARS)
    non_ascii_count = sum(1 for char in text if ord(char) > 127)
    newline_count = text.count("\n")
    long_fragment_count = len(_LONG_FRAGMENT_PATTERN.findall(text))
    return (
        math.ceil(dense_symbol_count / 12)
        + math.ceil(non_ascii_count / 3)
        + math.ceil(newline_count / 8)
        + long_fragment_count
    )


def _estimate_structure_overhead(value: Any) -> int:
    overhead = 0
    pending: list[Any] = [value]
    visited_nodes = 0
    while pending and visited_nodes < 4096:
        current = pending.pop()
        visited_nodes += 1
        if isinstance(current, dict):
            item_count = len(current)
            overhead += 2 + math.ceil(item_count / 6)
            pending.extend(current.values())
            continue
        if isinstance(current, list):
            item_count = len(current)
            overhead += 2 + math.ceil(item_count / 8)
            pending.extend(current)
    return overhead


def estimate_serialized_tokens(
    value: Any,
    *,
    approx_chars_per_token: int = 4,
    provider_name: str | None = None,
    model_id: str | None = None,
) -> int:
    text = _serialize_value(value)
    ratio = _resolve_ratio(
        approx_chars_per_token=approx_chars_per_token,
        provider_name=provider_name,
        model_id=model_id,
    )
    base_tokens = math.ceil(len(text) / ratio) if text else 0
    return max(1, base_tokens + _estimate_text_pressure_tokens(text) + _estimate_structure_overhead(value))


def estimate_message_tokens(
    messages: list[dict[str, Any]],
    *,
    approx_chars_per_token: int = 4,
    provider_name: str | None = None,
    model_id: str | None = None,
) -> int:
    normalized_messages = messages or []
    estimate = estimate_serialized_tokens(
        normalized_messages,
        approx_chars_per_token=approx_chars_per_token,
        provider_name=provider_name,
        model_id=model_id,
    )
    message_overhead = 0
    for message in normalized_messages:
        message_overhead += 3
        if not isinstance(message, dict):
            continue
        if message.get("role") == "tool":
            message_overhead += 2
        tool_calls = list(message.get("tool_calls") or [])
        if tool_calls:
            message_overhead += 4 * len(tool_calls)
    return max(1, estimate + message_overhead)


__all__ = [
    "estimate_message_tokens",
    "estimate_serialized_tokens",
]
