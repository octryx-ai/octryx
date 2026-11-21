"""Helpers for normalizing MCP SDK payloads."""

from collections.abc import Iterable
from typing import Any


def normalize_content_items(items: Iterable[Any]) -> list[dict[str, Any]]:
    """Convert MCP content items into plain dictionaries."""
    normalized: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "text"):
            normalized.append({"type": "text", "text": item.text})
        elif hasattr(item, "data"):
            normalized.append({"type": "data", "data": item.data})
        else:
            normalized.append({"type": "unknown", "content": str(item)})
    return normalized


def normalize_prompt_messages(messages: Iterable[Any]) -> list[dict[str, Any]]:
    """Convert MCP prompt messages into plain dictionaries."""
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if hasattr(message.content, "text"):
            content = message.content.text
        elif hasattr(message.content, "data"):
            content = message.content.data
        else:
            content = str(message.content)
        normalized.append(
            {
                "role": message.role if hasattr(message, "role") else "user",
                "content": content,
            }
        )
    return normalized
