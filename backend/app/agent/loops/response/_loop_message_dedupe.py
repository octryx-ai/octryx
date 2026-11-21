"""Message de-duplication helpers for loop-local runtime context."""

from __future__ import annotations

from typing import Any


def _normalized_content(content: Any) -> str:
    return " ".join(str(content or "").split())


def append_unique_system_message(
    messages: list[dict[str, Any]],
    content: str,
    *,
    recent_window: int | None = None,
) -> bool:
    """Append a system message only when the same instruction is not already present."""

    normalized = _normalized_content(content)
    if not normalized:
        return False
    haystack = messages[-recent_window:] if recent_window and recent_window > 0 else messages
    for message in reversed(haystack):
        if str(message.get("role") or "") == "system" and _normalized_content(message.get("content")) == normalized:
            return False
    messages.append({"role": "system", "content": content})
    return True


def append_unique_assistant_context(
    messages: list[dict[str, Any]],
    content: str,
    *,
    recent_window: int = 12,
) -> bool:
    """Keep guard feedback compact by not repeating identical assistant context."""

    normalized = _normalized_content(content)
    if not normalized:
        return False
    for message in reversed(messages[-recent_window:]):
        if str(message.get("role") or "") != "assistant":
            continue
        if message.get("tool_calls"):
            continue
        if _normalized_content(message.get("content")) == normalized:
            return False
    messages.append({"role": "assistant", "content": content})
    return True


def dedupe_runtime_control_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove exact duplicate standalone system messages from the prompt view."""

    seen_system_messages: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for message in messages:
        if str(message.get("role") or "") != "system":
            deduped.append(message)
            continue
        normalized = _normalized_content(message.get("content"))
        if normalized and normalized in seen_system_messages:
            continue
        if normalized:
            seen_system_messages.add(normalized)
        deduped.append(message)
    return deduped
