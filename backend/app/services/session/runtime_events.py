from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from ...time_utils import utc_isoformat, utc_now_aware
from .stream import session_stream_manager

RUNTIME_EVENT_SCHEMA_VERSION = 1

EVENT_TURN_STARTED = "turn_started"
EVENT_TOOL_CALL_BEGIN = "tool_call_begin"
EVENT_TOOL_CALL_END = "tool_call_end"

_MAX_STRING_CHARS = 1200
_MAX_ITEMS = 24
_MAX_DEPTH = 5
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "password",
    "secret",
    "session",
    "token",
)
_REDACTED = "[redacted]"

logger = logging.getLogger(__name__)


async def publish_turn_started(
    *,
    session_id: str,
    turn_id: str | None,
    user_message_id: str | None = None,
    project_id: str | None = None,
    agent_type: str | None = None,
    runtime_target_id: str | None = None,
    thinking_level: str | None = None,
    request_id: str | None = None,
) -> None:
    await _publish_runtime_event(
        session_id=session_id,
        event_type=EVENT_TURN_STARTED,
        payload={
            "turnId": turn_id,
            "userMessageId": user_message_id,
            "projectId": project_id,
            "agentType": agent_type,
            "runtimeTargetId": runtime_target_id,
            "thinkingLevel": thinking_level,
            "requestId": request_id,
        },
    )


async def publish_tool_call_begin(
    *,
    session_id: str,
    turn_id: str | None,
    tool_call_id: str | None,
    tool_name: str,
    parameters: Mapping[str, Any] | None,
    request_id: str | None,
) -> None:
    await _publish_runtime_event(
        session_id=session_id,
        event_type=EVENT_TOOL_CALL_BEGIN,
        payload={
            "turnId": turn_id,
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "parameters": _safe_value(parameters or {}),
            "requestId": request_id,
            "status": "in_progress",
        },
    )


async def publish_tool_call_end(
    *,
    session_id: str,
    turn_id: str | None,
    tool_call_id: str | None,
    persisted_tool_call_id: str,
    tool_name: str,
    status: str,
    duration_ms: int,
    artifact_id: str,
    result_preview: Any,
    cache: Mapping[str, Any] | None,
    request_id: str | None,
) -> None:
    await _publish_runtime_event(
        session_id=session_id,
        event_type=EVENT_TOOL_CALL_END,
        payload={
            "turnId": turn_id,
            "toolCallId": tool_call_id,
            "persistedToolCallId": persisted_tool_call_id,
            "toolName": tool_name,
            "status": str(status or "").strip().lower() or "unknown",
            "durationMs": max(0, int(duration_ms or 0)),
            "artifactId": artifact_id,
            "resultPreview": _safe_value(result_preview),
            "cache": _safe_value(cache) if cache else None,
            "requestId": request_id,
        },
    )


async def _publish_runtime_event(*, session_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
    try:
        await session_stream_manager.publish(
            session_id,
            event_type,
            {
                "schemaVersion": RUNTIME_EVENT_SCHEMA_VERSION,
                "eventId": str(uuid.uuid4()),
                "eventType": event_type,
                "createdAt": utc_isoformat(utc_now_aware()),
                **{key: value for key, value in payload.items() if value is not None},
            },
        )
    except Exception:
        logger.warning(
            "Failed to publish session runtime event",
            extra={"session_id": session_id, "event_type": event_type},
            exc_info=True,
        )


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= _MAX_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _bound_string(value)
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for index, (key, nested_value) in enumerate(value.items()):
            if index >= _MAX_ITEMS:
                safe["_truncated"] = True
                break
            key_text = _bound_string(str(key))
            if _is_sensitive_key(key_text):
                safe[key_text] = _REDACTED
            else:
                safe[key_text] = _safe_value(nested_value, depth=depth + 1)
        return safe
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        safe_items = [_safe_value(item, depth=depth + 1) for item in list(value)[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            safe_items.append("[truncated]")
        return safe_items
    return _bound_string(str(value))


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _bound_string(value: str) -> str:
    if len(value) <= _MAX_STRING_CHARS:
        return value
    return f"{value[:_MAX_STRING_CHARS]}...[truncated]"
