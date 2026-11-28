"""Observation of a Codex seat answer for usage and transcript: read, never rewritten."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .anthropic_stream import Observation
from .responses_events import (
    EVENT_COMPLETED,
    EVENT_CREATED,
    EVENT_ERROR,
    EVENT_FAILED,
    EVENT_INCOMPLETE,
    EVENT_ITEM_DONE,
    EVENT_TEXT_DELTA,
    EVENT_TEXT_DONE,
    TOOL_CALL_ITEMS,
    _finish,
    _observe_item,
    _upstream_code,
    anthropic_usage,
    kept_code,
)
from .sse_framing import split_sse_event, sse_event_fields

MAX_OBSERVED_EVENT_BYTES = 4 * 1024 * 1024


# No model check and no rewrite: the seat model is the person's own choice on their own subscription.
class CodexSeatObserver:
    def __init__(self, observation: Observation) -> None:
        self.observation = observation
        self._buffer = b""
        self._saw_delta = False

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        while (split := split_sse_event(self._buffer)) is not None:
            raw, self._buffer = split
            self._observe(raw)
        if len(self._buffer) > MAX_OBSERVED_EVENT_BYTES:
            self._buffer = b""

    def finish(self) -> None:
        raw, self._buffer = self._buffer, b""
        if raw.strip():
            self._observe(raw)

    def _observe(self, raw: bytes) -> None:
        name, data = sse_event_fields(raw)
        try:
            payload = json.loads(data) if data else None
        except ValueError:
            return
        if not isinstance(payload, Mapping):
            return
        name = str(payload.get("type") or name or "")
        observation = self.observation
        if name == EVENT_CREATED:
            observation.message_started = True
        elif name == EVENT_TEXT_DELTA:
            self._saw_delta = True
            observation.add_text(payload.get("delta"))
        elif name == EVENT_TEXT_DONE and not self._saw_delta:
            observation.add_text(payload.get("text"))
        elif name == EVENT_ITEM_DONE:
            item = payload.get("item")
            if isinstance(item, Mapping) and isinstance(item.get("type"), str) and item["type"] in TOOL_CALL_ITEMS:
                _observe_item(observation, item)
            elif isinstance(item, Mapping) and item.get("type") == HOSTED_SEARCH_ITEM:
                hosted_search(observation, item)
        elif name in (EVENT_COMPLETED, EVENT_INCOMPLETE):
            response = payload.get("response")
            _finish(observation, response if isinstance(response, Mapping) else {}, incomplete=name == EVENT_INCOMPLETE)
        elif name in (EVENT_ERROR, EVENT_FAILED):
            response = payload.get("response")
            if isinstance(response, Mapping):
                observation.usage.update(anthropic_usage(response.get("usage")))
            observation.upstream_error_type = kept_code(_upstream_code(payload))


HOSTED_SEARCH_ITEM = "web_search_call"
MAX_HOSTED_SEARCHES = 50


def hosted_search(observation: Observation, item: Mapping[str, Any]) -> None:
    if len(observation.hosted_searches) >= MAX_HOSTED_SEARCHES:
        return
    action = item.get("action") if isinstance(item.get("action"), Mapping) else {}
    target = action.get("query") or action.get("url") or ""
    observation.hosted_searches.append({
        "id": str(item.get("id") or "")[:64], "status": str(item.get("status") or "")[:32],
        "action": str(action.get("type") or "search")[:32], "target": str(target)[:500]})


def observe_responses_body(observation: Observation, body: Any) -> None:
    if not isinstance(body, Mapping):
        return
    observation.usage.update(anthropic_usage(body.get("usage")))
    observation.message_started = True
    output = body.get("output")
    for item in output if isinstance(output, list) else []:
        if isinstance(item, Mapping) and item.get("type") == HOSTED_SEARCH_ITEM:
            hosted_search(observation, item)
        else:
            _observe_item(observation, item)
    _finish(observation, body, incomplete=body.get("status") == "incomplete")


__all__ = ["HOSTED_SEARCH_ITEM", "CodexSeatObserver", "hosted_search", "observe_responses_body"]
