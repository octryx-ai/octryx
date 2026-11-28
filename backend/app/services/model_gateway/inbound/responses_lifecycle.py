"""The Responses stream events of a finished response, for an upstream that streamed only its text."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .responses_events import EVENT_CREATED, EVENT_ITEM_ADDED, EVENT_ITEM_DONE, EVENT_TEXT_DELTA


def lifecycle_events(terminal: str, response: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = response.get("output")
    items = [item for item in output if isinstance(item, Mapping)] if isinstance(output, list) else []
    events: list[dict[str, Any]] = [
        {"type": EVENT_CREATED, "response": {**response, "status": "in_progress", "output": []}}]
    for index, item in enumerate(items):
        message = item.get("type") == "message"
        started = {**item, "status": "in_progress", "content": []} if message else dict(item)
        events.append({"type": EVENT_ITEM_ADDED, "output_index": index, "item": started})
        content = item.get("content") if message else None
        for part_index, part in enumerate(content if isinstance(content, list) else []):
            if isinstance(part, Mapping) and part.get("type") == "output_text" and part.get("text"):
                events.append({"type": EVENT_TEXT_DELTA, "item_id": item.get("id"), "output_index": index,
                               "content_index": part_index, "delta": part["text"]})
        events.append({"type": EVENT_ITEM_DONE, "output_index": index, "item": dict(item)})
    events.append({"type": terminal, "response": dict(response)})
    return events


__all__ = ["lifecycle_events"]
