"""The scanned segments of a platform model request (an OpenAI-style chat)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..content_detection.scanner import Segment
from ..content_detection.vocabulary import SOURCE_DOCUMENT, SOURCE_PROMPT, SOURCE_SYSTEM, SOURCE_TOOL_RESULT

#: Media parts: the detectors read text, so a media part is an unreadable segment (``complete`` false).
MEDIA_BLOCK_TYPES = frozenset({"image", "image_url", "input_image", "file"})


# An unknown shape is scanned as its JSON text, so nothing in a message escapes the scan.
def _serialized(value: Any) -> dict[str, Any]:
    return {"type": "text", "text": json.dumps(value, ensure_ascii=False, default=str)}


def _blocks(content: Any) -> list[Mapping[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block if isinstance(block, Mapping) else _serialized(block) for block in content]
    return [_serialized(content)]


def _block_segments(block: Mapping[str, Any], source: str) -> list[Segment]:
    kind = str(block.get("type") or "")
    if kind == "text":
        text = block.get("text")
        if text is not None and not isinstance(text, str):
            return _block_segments(_serialized(block), source)
        return [Segment(text, source)] if text else []
    if kind == "tool_result":
        return [item for inner in _blocks(block.get("content")) for item in _block_segments(inner, SOURCE_TOOL_RESULT)]
    if kind == "document":
        data = block.get("source") if isinstance(block.get("source"), Mapping) else {}
        if data.get("type") == "text" and isinstance(data.get("data"), str):
            return [Segment(data["data"], SOURCE_DOCUMENT)]
        return [Segment("", SOURCE_DOCUMENT, readable=False)]
    if kind in MEDIA_BLOCK_TYPES:
        return [Segment("", source if source == SOURCE_TOOL_RESULT else SOURCE_DOCUMENT, readable=False)]
    return _block_segments(_serialized(block), source)


def _last_assistant(messages: list[Any]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], Mapping) and messages[index].get("role") == "assistant":
            return index
    return -1


# The system messages and the newest turn: earlier turns were scanned when new and carry on as principal.sensitive.
def chat_segments(messages: list[Mapping[str, Any]]) -> list[Segment]:
    segments: list[Segment] = []
    last = _last_assistant(messages)
    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        if role == "system":
            source = SOURCE_SYSTEM
        elif index <= last:
            continue
        elif role == "tool":
            source = SOURCE_TOOL_RESULT
        elif role == "user":
            source = SOURCE_PROMPT
        else:
            continue
        segments += [item for block in _blocks(message.get("content")) for item in _block_segments(block, source)]
    return segments


__all__ = ["MEDIA_BLOCK_TYPES", "chat_segments"]
