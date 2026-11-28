"""Relay of LiteLLM's OpenAI Responses answers to the client (the /openai route for Codex)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..litellm.alias_catalog import AliasEntry
from ..litellm.errors import (
    GATEWAY_STATE_FALLBACK_VIOLATION,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
    GATEWAY_STATE_UNAVAILABLE,
)
from .anthropic_stream import (
    MAX_SSE_EVENT_BYTES,
    REASON_EVENT_TOO_LARGE,
    REASON_MODEL_NOT_ADMITTED,
    REASON_RESPONSE_NOT_JSON,
    REASON_UPSTREAM_STREAM_ERROR,
    Observation,
    RelayRefused,
    model_match,
)
from .refusals import ERROR_TYPE_API
from .responses_events import (
    _ERROR_TYPE_FOR_CODE,
    EVENT_ARGUMENTS_DONE,
    EVENT_COMPLETED,
    EVENT_CREATED,
    EVENT_ERROR,
    EVENT_FAILED,
    EVENT_INCOMPLETE,
    EVENT_ITEM_ADDED,
    EVENT_ITEM_DONE,
    EVENT_TEXT_DELTA,
    EVENT_TEXT_DONE,
    TOOL_CALL_ITEMS,
    _encode,
    _finish,
    _observe_item,
    _upstream_code,
    _with_alias,
    anthropic_usage,
    gateway_failed_event,
    kept_code,
)
from .responses_lifecycle import lifecycle_events
from .responses_namespaces import NamespaceMap
from .sse_framing import split_sse_event, sse_event_fields

REASON_MISSING_RESPONSE_CREATED = "stream_missing_response_created"
# What a stream may hold while its model is not named yet (``ResponsesSseRelay._hold``).
MAX_HELD_BYTES = 32 * 1024 * 1024
# An SSE comment: ignored by every SSE parser, keeps idle connections (proxies) open.
KEEPALIVE_COMMENT = b": keepalive\n\n"


class ResponsesSseRelay:
    _PARSED = frozenset({EVENT_CREATED, "response.in_progress", EVENT_COMPLETED, EVENT_INCOMPLETE, EVENT_FAILED,
                         EVENT_ERROR, EVENT_TEXT_DELTA, EVENT_TEXT_DONE, EVENT_ITEM_DONE, EVENT_ITEM_ADDED,
                         EVENT_ARGUMENTS_DONE})
    # LiteLLM fakes the stream of a model its catalog does not know (every route added in Admin › Models): the full
    # answer as text deltas, then response.completed, with no response.created and no output items.
    _FAKED_STREAM_START = frozenset({EVENT_TEXT_DELTA, EVENT_COMPLETED})

    def __init__(self, *, entry: AliasEntry, observation: Observation, names: NamespaceMap | None = None):
        self._entry = entry
        self.observation = observation
        # The request's flattened namespace tools (``responses_namespaces``): calls get their namespace back.
        self._names = names if names else None
        self._buffer = b""
        self._pending: list[bytes] = []
        self._saw_delta = False
        self._response_id = ""
        # An upstream whose ``response.created`` names no model (llama.cpp's server names it only in
        # ``response.completed``): every event is held until one names the model, which is then checked before
        # anything reaches the client. The answer then arrives at once instead of streamed.
        self._deferred_created: Mapping[str, Any] | None = None
        self._held: list[tuple[str, Mapping[str, Any], bytes]] = []
        self._held_bytes = 0
        self._faked = False

    @property
    def verified(self) -> bool:
        return self.observation.message_started

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer += chunk
        out: list[bytes] = []
        while (split := split_sse_event(self._buffer)) is not None:
            raw, self._buffer = split
            out.extend(self._handle(raw))
        if len(self._buffer) > MAX_SSE_EVENT_BYTES:
            raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_EVENT_TOO_LARGE)
        return out

    def finish(self) -> list[bytes]:
        raw, self._buffer = self._buffer, b""
        out = self._handle(raw) if raw.strip() else []
        if self._deferred_created is not None and not self.verified:
            raise RelayRefused(GATEWAY_STATE_FALLBACK_VIOLATION, REASON_MODEL_NOT_ADMITTED)  # no event named one
        if self._faked:
            raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_MISSING_RESPONSE_CREATED)
        return out

    def _handle(self, raw: bytes) -> list[bytes]:
        name, data = sse_event_fields(raw)
        payload: Any = None
        if name in self._PARSED or not name:
            try:
                payload = json.loads(data) if data else None
            except ValueError:
                payload = None
            if isinstance(payload, Mapping) and isinstance(payload.get("type"), str):
                name = payload["type"]  # the data's own type decides (Codex reads only the data)
        payload = payload if isinstance(payload, Mapping) else {}
        if self._faked:
            return self._faked_stream(name, payload, raw)
        if self._deferred_created is not None and not self.verified:
            return self._hold(name, payload, raw)
        if not self.verified:
            if not name:  # no type at all (``[DONE]``, a comment): held until the model is checked
                self._pending.append(raw)
                return []
            if name in (EVENT_ERROR, EVENT_FAILED):
                self.observation.usage.update(anthropic_usage((payload.get("response") or {}).get("usage")
                                                              if isinstance(payload.get("response"), Mapping)
                                                              else None))
                code = _upstream_code(payload)
                raise RelayRefused(GATEWAY_STATE_UNAVAILABLE, REASON_UPSTREAM_STREAM_ERROR,
                                   upstream_error_type=_ERROR_TYPE_FOR_CODE.get(code, ERROR_TYPE_API))
            if name in self._FAKED_STREAM_START:
                self._faked = True
                return self._faked_stream(name, payload, raw)
            if name != EVENT_CREATED:
                raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_MISSING_RESPONSE_CREATED)
            response = payload.get("response")
            if isinstance(response, Mapping) and not response.get("model"):
                self._deferred_created = payload
                return []
            pending, self._pending = self._pending, []
            return [*pending, self._created(payload)]
        return [self._observe(name, payload, raw)]

    # An upstream that names the model only later (llama.cpp: in response.completed) has its events held until one does.
    def _hold(self, name: str, payload: Mapping[str, Any], raw: bytes) -> list[bytes]:
        response = payload.get("response")
        model = response.get("model") if isinstance(response, Mapping) else None
        if name in (EVENT_ERROR, EVENT_FAILED) and not model:
            code = _upstream_code(payload)
            raise RelayRefused(GATEWAY_STATE_UNAVAILABLE, REASON_UPSTREAM_STREAM_ERROR,
                               upstream_error_type=_ERROR_TYPE_FOR_CODE.get(code, ERROR_TYPE_API))
        self._held.append((name, payload, raw))
        self._held_bytes += len(raw)
        if self._held_bytes > MAX_HELD_BYTES:
            raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_EVENT_TOO_LARGE)
        if not model:
            return []
        created = dict(self._deferred_created or {})
        created["response"] = {**dict(created.get("response") or {}), "model": model}
        self._deferred_created = None
        pending, self._pending = self._pending, []
        out = [*pending, self._created(created)]
        held, self._held = self._held, []
        out += [self._observe(held_name, held_payload, held_raw) for held_name, held_payload, held_raw in held]
        return out

    # Held until response.completed carries the whole answer; its lifecycle is then built from it.
    def _faked_stream(self, name: str, payload: Mapping[str, Any], raw: bytes) -> list[bytes]:
        if name in (EVENT_ERROR, EVENT_FAILED):
            code = _upstream_code(payload)
            raise RelayRefused(GATEWAY_STATE_UNAVAILABLE, REASON_UPSTREAM_STREAM_ERROR,
                               upstream_error_type=_ERROR_TYPE_FOR_CODE.get(code, ERROR_TYPE_API))
        response = payload.get("response")
        if name != EVENT_COMPLETED or not isinstance(response, Mapping):
            self._held_bytes += len(raw)
            if self._held_bytes > MAX_HELD_BYTES:
                raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_EVENT_TOO_LARGE)
            return []
        self._faked = False
        created, *events = lifecycle_events(name, response)
        pending, self._pending = self._pending, []
        out = [*pending, self._created(created)]
        return out + [self._observe(event["type"], event, _encode(event["type"], event)) for event in events]

    def _created(self, payload: Mapping[str, Any]) -> bytes:
        response = payload.get("response")
        response = response if isinstance(response, Mapping) else {}
        matched = model_match(self._entry, response.get("model"))
        if not matched:
            raise RelayRefused(GATEWAY_STATE_FALLBACK_VIOLATION, REASON_MODEL_NOT_ADMITTED)
        self.observation.model_match = matched
        self.observation.message_started = True
        self._response_id = str(response.get("id") or "")[:200]
        return _encode(EVENT_CREATED, _with_alias(payload, self._entry.alias))

    def _observe(self, name: str, payload: Mapping[str, Any], raw: bytes) -> bytes:
        observation = self.observation
        if name == EVENT_TEXT_DELTA:
            self._saw_delta = True
            observation.add_text(payload.get("delta"))
        elif name == EVENT_TEXT_DONE and not self._saw_delta:
            observation.add_text(payload.get("text"))
        elif name == EVENT_ITEM_DONE:
            item = payload.get("item")
            if isinstance(item, Mapping) and isinstance(item.get("type"), str) and item["type"] in TOOL_CALL_ITEMS:
                _observe_item(observation, item)
        elif name in (EVENT_ERROR, EVENT_FAILED):
            response = payload.get("response")
            if isinstance(response, Mapping):
                observation.usage.update(anthropic_usage(response.get("usage")))
            code = _upstream_code(payload)
            observation.upstream_error_type = kept_code(code)
            return gateway_failed_event(code, self._entry.alias, self._response_id)
        elif name in (EVENT_COMPLETED, EVENT_INCOMPLETE):
            response = payload.get("response")
            _finish(observation, response if isinstance(response, Mapping) else {},
                    incomplete=name == EVENT_INCOMPLETE)
        restored = self._names.restore_payload(payload) if self._names is not None else payload
        if isinstance(payload.get("response"), Mapping):
            return _encode(name, _with_alias(restored, self._entry.alias))
        if restored is not payload:
            return _encode(name, restored)
        return raw


def relay_json_response(entry: AliasEntry, body: Any, observation: Observation,
                        names: NamespaceMap | None = None) -> dict[str, Any]:
    if not isinstance(body, Mapping):
        raise RelayRefused(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_RESPONSE_NOT_JSON)
    observation.usage.update(anthropic_usage(body.get("usage")))
    matched = model_match(entry, body.get("model"))
    if not matched:
        raise RelayRefused(GATEWAY_STATE_FALLBACK_VIOLATION, REASON_MODEL_NOT_ADMITTED)
    observation.model_match = matched
    observation.message_started = True
    output = body.get("output")
    for item in output if isinstance(output, list) else []:
        _observe_item(observation, item)
    _finish(observation, body, incomplete=body.get("status") == "incomplete")
    restored = names.restore_payload(body) if names else body
    return {**restored, "model": entry.alias}


__all__ = [
    "KEEPALIVE_COMMENT",
    "REASON_MISSING_RESPONSE_CREATED",
    "ResponsesSseRelay",
    "relay_json_response",
]
