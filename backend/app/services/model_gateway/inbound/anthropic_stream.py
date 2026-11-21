"""Relay of LiteLLM's Anthropic Messages responses to the client.

Streaming: server-sent events are split incrementally and every event is
forwarded with the bytes it arrived with, except

- ``message_start``, whose ``message.model`` is rewritten to the Octryx
  alias (the upstream model group is never shown to the client), and
- ``error``, whose upstream message is replaced by a fixed gateway message (the
  Anthropic error ``type`` is kept so the client's retry logic still works).

Before anything is forwarded the served model is checked: ``message_start`` must
come first (pings may precede it) and must name the admitted model group or one
of the alias' declared ``served_model_ids``. Anything else is a refusal while
the client has received nothing yet.

The relay observes usage (``message_start`` and ``message_delta``), the stop
reason, a bounded copy of the assistant text and the ``tool_use`` blocks, for
usage accounting and the transcript.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..litellm.alias_catalog import AliasEntry
from ..litellm.errors import (
    GATEWAY_STATE_FALLBACK_VIOLATION,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
    GATEWAY_STATE_UNAVAILABLE,
)
from .refusals import ANTHROPIC_ERROR_TYPES, ERROR_TYPE_API
from .sse_framing import split_sse_event, sse_event_fields

logger = logging.getLogger(__name__)

# One SSE event larger than this without a terminating blank line is a
# malformed stream, not something to buffer without limit.
MAX_SSE_EVENT_BYTES = 4 * 1024 * 1024
MAX_OBSERVED_TEXT_CHARS = 20_000
MAX_OBSERVED_TOOL_USES = 64
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

REASON_MISSING_MESSAGE_START = "stream_missing_message_start"
REASON_MODEL_NOT_ADMITTED = "served_model_not_admitted"
REASON_EVENT_TOO_LARGE = "stream_event_too_large"
REASON_RESPONSE_NOT_JSON = "response_not_json_object"
REASON_UPSTREAM_STREAM_ERROR = "upstream_stream_error"

MODEL_MATCH_GROUP = "model_group"
MODEL_MATCH_SERVED_ID = "served_model_id"

PING_EVENT = b'event: ping\ndata: {"type": "ping"}\n\n'


class RelayRefused(Exception):  # noqa: N818 - a refusal value carried as an exception
    """The upstream answer violates the served-model or stream contract."""

    def __init__(self, state: str, reason: str, *, upstream_error_type: str = ""):
        super().__init__(reason)
        self.state = state
        self.reason = reason
        # Set when the upstream itself failed before ``message_start``; the
        # route keeps its retry semantics (429/529/5xx) instead of a violation.
        self.upstream_error_type = upstream_error_type


@dataclass
class Observation:
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""
    text: str = ""
    tool_uses: list[dict[str, str]] = field(default_factory=list)
    model_match: str = ""
    message_started: bool = False
    stream_completed: bool = False
    upstream_error_type: str = ""
    # Codex's provider-hosted web searches in this answer (``web_search_call`` items: the query, its status); they
    # leave from the provider, so they are no tool call of the conversation.
    hosted_searches: list[dict[str, str]] = field(default_factory=list)

    def add_text(self, value: Any) -> None:
        if isinstance(value, str) and len(self.text) < MAX_OBSERVED_TEXT_CHARS:
            self.text = (self.text + value)[:MAX_OBSERVED_TEXT_CHARS]

    def add_tool_use(self, block: Mapping[str, Any]) -> None:
        if len(self.tool_uses) < MAX_OBSERVED_TOOL_USES:
            self.tool_uses.append({"id": str(block.get("id") or "")[:64], "name": str(block.get("name") or "")[:200]})

    def add_usage(self, usage: Any) -> None:
        if not isinstance(usage, Mapping):
            return
        for key in USAGE_KEYS:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                self.usage[key] = value


def _loggable_model_id(value: str) -> str:
    """The served model id for the operator log: narrow charset and bounded, else a marker."""

    if value and len(value) <= 120 and all(ch.isalnum() or ch in "._:-/@" for ch in value):
        return value
    return "<unprintable>"


def model_match(entry: AliasEntry, served_model: Any) -> str:
    """How the served model relates to the admitted alias; empty = not admitted.

    A refusal logs the observed id (narrow charset only), because declaring it in
    the alias' ``served_model_ids`` is the operator's explicit fix.
    """

    value = served_model.strip() if isinstance(served_model, str) else ""
    if value and value == entry.model_group:
        return MODEL_MATCH_GROUP
    if value and value in entry.served_model_ids:
        return MODEL_MATCH_SERVED_ID
    logger.warning(
        "model_gateway_served_model_not_admitted alias=%s observed=%s", entry.alias, _loggable_model_id(value)
    )
    return ""


def _encode_event(name: str, payload: Mapping[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


def gateway_error_event(error_type: str) -> bytes:
    kind = error_type if error_type in ANTHROPIC_ERROR_TYPES else ERROR_TYPE_API
    message = f"Octryx gateway: upstream_stream_error ({kind}). The model stream failed; retry the request."
    return _encode_event("error", {"type": "error", "error": {"type": kind, "message": message}})


class SseRelay:
    """Incremental SSE relay for one streamed response."""

    _PARSED = frozenset({"message_start", "message_delta", "message_stop", "content_block_start",
                         "content_block_delta", "error"})

    def __init__(self, *, entry: AliasEntry, observation: Observation):
        self._entry = entry
        self.observation = observation
        self._buffer = b""
        self._pending: list[bytes] = []

    @property
    def verified(self) -> bool:
        return self.observation.message_started

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer += chunk
        out: list[bytes] = []
        while True:
            split = split_sse_event(self._buffer)
            if split is None:
                break
            raw, self._buffer = split
            out.extend(self._handle(raw))
        if len(self._buffer) > MAX_SSE_EVENT_BYTES:
            raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_EVENT_TOO_LARGE)
        return out

    def finish(self) -> list[bytes]:
        """Flush a trailing event that ended without a blank line."""

        raw, self._buffer = self._buffer, b""
        return self._handle(raw) if raw.strip() else []

    def _handle(self, raw: bytes) -> list[bytes]:
        name, data = sse_event_fields(raw)
        payload: Any = None
        if name in self._PARSED or not name:
            try:
                payload = json.loads(data) if data else None
            except ValueError:
                payload = None
            if not name and isinstance(payload, Mapping):
                name = str(payload.get("type") or "")
        payload = payload if isinstance(payload, Mapping) else {}
        if not self.verified:
            if name == "ping" or not name:
                self._pending.append(raw)
                return []
            if name == "error":
                error = payload.get("error")
                kind = str(error.get("type") or "") if isinstance(error, Mapping) else ""
                raise RelayRefused(
                    GATEWAY_STATE_UNAVAILABLE,
                    REASON_UPSTREAM_STREAM_ERROR,
                    upstream_error_type=kind if kind in ANTHROPIC_ERROR_TYPES else ERROR_TYPE_API,
                )
            if name != "message_start":
                raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_MISSING_MESSAGE_START)
            pending, self._pending = self._pending, []
            return [*pending, self._message_start(payload)]
        return [self._observe(name, payload, raw)]

    def _message_start(self, payload: Mapping[str, Any]) -> bytes:
        message = payload.get("message")
        message = dict(message) if isinstance(message, Mapping) else {}
        # Usage first: a refused call was still billed upstream and is recorded.
        self.observation.add_usage(message.get("usage"))
        matched = model_match(self._entry, message.get("model"))
        if not matched:
            raise RelayRefused(GATEWAY_STATE_FALLBACK_VIOLATION, REASON_MODEL_NOT_ADMITTED)
        self.observation.model_match = matched
        self.observation.message_started = True
        message["model"] = self._entry.alias
        return _encode_event("message_start", {**payload, "message": message})

    def _observe(self, name: str, payload: Mapping[str, Any], raw: bytes) -> bytes:
        observation = self.observation
        if name == "content_block_start":
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
            observation.upstream_error_type = str(error.get("type") or "") if isinstance(error, Mapping) else ""
            return gateway_error_event(observation.upstream_error_type)
        return raw


def relay_json_message(entry: AliasEntry, body: Any, observation: Observation) -> dict[str, Any]:
    """Non-streaming: check and rewrite the model, observe usage and content."""

    if not isinstance(body, Mapping):
        raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_RESPONSE_NOT_JSON)
    observation.add_usage(body.get("usage"))
    matched = model_match(entry, body.get("model"))
    if not matched:
        raise RelayRefused(GATEWAY_STATE_FALLBACK_VIOLATION, REASON_MODEL_NOT_ADMITTED)
    observation.model_match = matched
    observation.message_started = True
    observation.stream_completed = True
    stop_reason = body.get("stop_reason")
    observation.stop_reason = stop_reason[:64] if isinstance(stop_reason, str) else ""
    content = body.get("content")
    for block in content if isinstance(content, list) else []:
        if isinstance(block, Mapping) and block.get("type") == "text":
            observation.add_text(block.get("text"))
        elif isinstance(block, Mapping) and block.get("type") == "tool_use":
            observation.add_tool_use(block)
    return {**body, "model": entry.alias}


__all__ = [
    "MAX_SSE_EVENT_BYTES",
    "PING_EVENT",
    "Observation",
    "RelayRefused",
    "SseRelay",
    "gateway_error_event",
    "model_match",
    "relay_json_message",
]
