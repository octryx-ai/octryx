"""The OpenAI Responses events the inbound relay and the Codex seat observer read."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .anthropic_stream import Observation
from .openai_view import LOCAL_SHELL_TOOL, evidence_names
from .refusals import ERROR_TYPE_OVERLOADED, ERROR_TYPE_RATE_LIMIT, OPENAI_CONTEXT_LENGTH_CODE

EVENT_CREATED = "response.created"
EVENT_COMPLETED = "response.completed"
EVENT_INCOMPLETE = "response.incomplete"
EVENT_FAILED = "response.failed"
EVENT_ERROR = "error"
EVENT_TEXT_DELTA = "response.output_text.delta"
EVENT_TEXT_DONE = "response.output_text.done"
EVENT_ITEM_DONE = "response.output_item.done"
EVENT_ITEM_ADDED = "response.output_item.added"
EVENT_ARGUMENTS_DONE = "response.function_call_arguments.done"

TOOL_CALL_ITEMS = frozenset({"function_call", "custom_tool_call", "local_shell_call"})
STOP_END_TURN = "end_turn"
STOP_TOOL_USE = "tool_use"
STOP_MAX_TOKENS = "max_tokens"

# Upstream error codes the client may see (they steer its retry/compaction); every other code is ``server_error``.
_KEPT_CODES = frozenset({"rate_limit_exceeded", "server_is_overloaded", "slow_down", OPENAI_CONTEXT_LENGTH_CODE})
_CODE_SERVER_ERROR = "server_error"
# The Anthropic error type ``relay.refusal_for_relay`` keys its retry status on (429 / 529 / 502).
_ERROR_TYPE_FOR_CODE = {"rate_limit_exceeded": ERROR_TYPE_RATE_LIMIT, "slow_down": ERROR_TYPE_RATE_LIMIT,
                        "server_is_overloaded": ERROR_TYPE_OVERLOADED}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def anthropic_usage(usage: Any) -> dict[str, int]:
    if not isinstance(usage, Mapping):
        return {}
    total_in, output = _int(usage.get("input_tokens")), _int(usage.get("output_tokens"))
    details = usage.get("input_tokens_details")
    cached = _int(details.get("cached_tokens")) if isinstance(details, Mapping) else None
    mapped: dict[str, int] = {}
    if total_in is not None:
        mapped["input_tokens"] = max(0, total_in - (cached or 0))
        if cached is not None:
            mapped["cache_read_input_tokens"] = min(cached, total_in)
    if output is not None:
        mapped["output_tokens"] = output
    return mapped


def _upstream_code(payload: Mapping[str, Any]) -> str:
    for holder in (payload, payload.get("error"), (payload.get("response") or {}).get("error")
                   if isinstance(payload.get("response"), Mapping) else None):
        code = holder.get("code") if isinstance(holder, Mapping) else None
        if isinstance(code, str) and code:
            return code
    return ""


def kept_code(code: str) -> str:
    return code if code in _KEPT_CODES else _CODE_SERVER_ERROR


def _encode(name: str, payload: Mapping[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


def gateway_failed_event(code: str, alias: str, response_id: str = "") -> bytes:
    kept = kept_code(code)
    message = f"Octryx gateway: upstream_stream_error ({kept}). The model stream failed; retry the request."
    return _encode(EVENT_FAILED, {"type": EVENT_FAILED, "response": {
        "id": response_id, "object": "response", "status": "failed", "model": alias, "output": [],
        "error": {"code": kept, "message": message}}})


def _observe_item(observation: Observation, item: Any) -> None:
    if not isinstance(item, Mapping):
        return
    kind = item.get("type")
    if kind in TOOL_CALL_ITEMS:
        name = LOCAL_SHELL_TOOL if kind == "local_shell_call" else str(item.get("name") or "")
        if item.get("namespace"):
            name = f"{item['namespace']}__{name}"
        observation.add_tool_use({"id": item.get("call_id") or item.get("id"), "name": evidence_names(name, {})[0]})
    elif kind == "message":
        for part in item.get("content") if isinstance(item.get("content"), list) else []:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                observation.add_text(part.get("text"))


def _finish(observation: Observation, response: Mapping[str, Any], *, incomplete: bool) -> None:
    observation.usage.update(anthropic_usage(response.get("usage")))
    if incomplete:
        details = response.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, Mapping) else None
        observation.stop_reason = STOP_MAX_TOKENS if reason == "max_output_tokens" else str(reason or "incomplete")[:64]
    else:
        observation.stop_reason = STOP_TOOL_USE if observation.tool_uses else STOP_END_TURN
    observation.stream_completed = True


def _with_alias(payload: Mapping[str, Any], alias: str) -> dict[str, Any]:
    response = payload.get("response")
    if not isinstance(response, Mapping):
        return dict(payload)
    return {**payload, "response": {**response, "model": alias}}


__all__ = [
    "TOOL_CALL_ITEMS",
    "anthropic_usage",
    "gateway_failed_event",
    "kept_code",
]
