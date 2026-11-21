"""What the seat route observes of Anthropic's answer for the transcript (``seat``); the bytes stay unchanged."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .anthropic_stream import Observation
from .sse_framing import split_sse_event, sse_event_fields


class SeatSseObserver:
    """Observes an Anthropic event stream for the transcript without changing a single byte of it."""

    def __init__(self, observation: Observation) -> None:
        self.observation = observation
        self._buffer = b""

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        while (split := split_sse_event(self._buffer)) is not None:
            raw, self._buffer = split
            self._observe(raw)
        if len(self._buffer) > 4 * 1024 * 1024:
            self._buffer = b""  # an oversized event is not observed; the bytes were relayed anyway

    def finish(self) -> None:
        raw, self._buffer = self._buffer, b""
        if raw.strip():
            self._observe(raw)

    def _observe(self, raw: bytes) -> None:
        name, data = sse_event_fields(raw)
        try:
            payload = json.loads(data) if data else {}
        except ValueError:
            return
        if not isinstance(payload, Mapping):
            return
        name = name or str(payload.get("type") or "")
        observe_event(self.observation, name, payload)


def observe_event(observation: Observation, name: str, payload: Mapping[str, Any]) -> None:
    if name == "message_start":
        message = payload.get("message") if isinstance(payload.get("message"), Mapping) else {}
        observation.add_usage(message.get("usage"))
        observation.message_started = True
    elif name == "content_block_start":
        block = payload.get("content_block")
        if isinstance(block, Mapping) and block.get("type") == "tool_use":
            observation.add_tool_use(block)
    elif name == "content_block_delta":
        delta = payload.get("delta")
        if isinstance(delta, Mapping) and delta.get("type") == "text_delta":
            observation.add_text(delta.get("text"))
    elif name == "message_delta":
        observation.add_usage(payload.get("usage"))
        delta = payload.get("delta")
        stop_reason = delta.get("stop_reason") if isinstance(delta, Mapping) else None
        if isinstance(stop_reason, str) and stop_reason:
            observation.stop_reason = stop_reason[:64]
    elif name == "message_stop":
        observation.stream_completed = True
    elif name == "error":
        error = payload.get("error")
        observation.upstream_error_type = str(error.get("type") or "")[:64] if isinstance(error, Mapping) else ""


def observe_message(observation: Observation, body: Any) -> None:
    """Non-streaming answer: usage, stop reason, text and tool uses."""
    if not isinstance(body, Mapping):
        return
    observation.add_usage(body.get("usage"))
    observation.message_started = observation.stream_completed = body.get("type") == "message"
    stop_reason = body.get("stop_reason")
    observation.stop_reason = stop_reason[:64] if isinstance(stop_reason, str) else ""
    for block in body.get("content") if isinstance(body.get("content"), list) else []:
        if isinstance(block, Mapping) and block.get("type") == "text":
            observation.add_text(block.get("text"))
        elif isinstance(block, Mapping) and block.get("type") == "tool_use":
            observation.add_tool_use(block)


__all__ = ["SeatSseObserver", "observe_event", "observe_message"]
