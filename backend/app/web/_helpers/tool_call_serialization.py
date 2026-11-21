"""Serializers for tool calls and the execution events they report."""

from pathlib import Path

from ...models import ToolCall
from .serialization import _serialize_timestamp

__all__ = ["_serialize_tool_call"]


def _extract_execution_event(result: object) -> dict | None:
    if not isinstance(result, dict):
        return None
    event = result.get("execution_event")
    if isinstance(event, dict):
        return event
    preview = result.get("preview")
    if isinstance(preview, dict):
        compact = preview.get("compact_result")
        if isinstance(compact, dict) and isinstance(compact.get("execution_event"), dict):
            return compact["execution_event"]
    return None


def _extract_execution_events(result: object) -> list[dict]:
    if not isinstance(result, dict):
        return []
    events = result.get("execution_events")
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]
    preview = result.get("preview")
    if isinstance(preview, dict):
        compact = preview.get("compact_result")
        compact_events = compact.get("execution_events") if isinstance(compact, dict) else None
        if isinstance(compact_events, list):
            return [event for event in compact_events if isinstance(event, dict)]
    return []


def _serialize_tool_call(tool_call: ToolCall, *, workspace_root: "Path | None" = None) -> dict:
    from .workspace_artifacts import _serialize_tool_artifacts

    result = tool_call.result or {}
    return {
        "id": tool_call.id,
        "messageId": tool_call.message_id,
        "toolName": tool_call.tool_name,
        "parameters": tool_call.parameters or {},
        "result": result,
        "executionEvent": _extract_execution_event(result),
        "executionEvents": _extract_execution_events(result),
        "artifacts": _serialize_tool_artifacts(tool_call, workspace_root=workspace_root),
        "status": tool_call.status,
        "durationMs": tool_call.duration_ms,
        "createdAt": _serialize_timestamp(tool_call.created_at),
    }
