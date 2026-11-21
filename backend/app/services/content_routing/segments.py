"""The scanned segments of a platform model request (an OpenAI-style chat: the governed driver, the provider wrapper).

What is new on a call is scanned: the system prompt and the newest turn (everything after the last assistant
message: the user's text, tool results, inline system texts, documents). Earlier turns were scanned when they
were new; a conversation that already contained a category carries it as ``principal.sensitive``.

Content the scan cannot read — an image, a base64 document — is an unreadable segment and makes the scan
incomplete; policies decide what an incomplete scan means. Content of any other shape (an unknown block type, a
non-text block field, content that is neither text nor a block list) is scanned as its JSON text, so nothing in
a message escapes the scan. (The inbound gateway reads its forwarded bodies whole: ``gateway``.)
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..content_detection.scanner import Segment
from ..content_detection.vocabulary import SOURCE_DOCUMENT, SOURCE_PROMPT, SOURCE_SYSTEM, SOURCE_TOOL_RESULT

#: Media parts: the detectors read text, so a media part is an unreadable segment (``complete`` false).
MEDIA_BLOCK_TYPES = frozenset({"image", "image_url", "input_image", "file"})


def _serialized(value: Any) -> dict[str, Any]:
    """A shape the scan does not know, as a text block of its JSON."""
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


def chat_segments(messages: list[Mapping[str, Any]]) -> list[Segment]:
    """An OpenAI-style chat request (the platform's governed driver): system messages and the newest turn."""
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
