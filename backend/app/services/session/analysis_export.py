"""Structured session export for Codex/LLM analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, ToolCall, TurnTrace, User
from ...time_utils import utc_isoformat
from ..content_security.knowledge_fence import unfenced_result
from .export_bundle import (
    SessionExportBundle,
    load_session_export_bundle,
    session_export_filename,
    session_export_title,
    user_export_payload,
)


@dataclass(frozen=True, slots=True)
class SessionAnalysisExport:
    content: bytes
    filename: str


async def build_session_analysis_export(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    exported_by: User | None = None,
) -> SessionAnalysisExport:
    bundle = await load_session_export_bundle(
        db,
        session_id=session_id,
        user_id=user_id,
        exported_by=exported_by,
    )
    title = session_export_title(bundle.session, fallback="Chat Analysis Export")
    # Exported for reviewers and other systems: fence markers stay with the model's own input.
    payload = unfenced_result(_session_analysis_payload(title=title, bundle=bundle))
    content = json.dumps(payload, ensure_ascii=False, sort_keys=False, indent=2, default=str).encode("utf-8")
    filename = session_export_filename(title=title, session_id=bundle.session.id, suffix="analysis.json")
    return SessionAnalysisExport(content=content, filename=filename)


def _session_analysis_payload(*, title: str, bundle: SessionExportBundle) -> dict[str, Any]:
    tool_calls_by_message_id: dict[str, list[ToolCall]] = {}
    for tool_call in bundle.tool_calls:
        if tool_call.message_id:
            tool_calls_by_message_id.setdefault(str(tool_call.message_id), []).append(tool_call)

    traces_by_message_id: dict[str, list[TurnTrace]] = {}
    for trace in bundle.turn_traces:
        if trace.message_id:
            traces_by_message_id.setdefault(str(trace.message_id), []).append(trace)

    return {
        "schema": "octryx.chat.analysis.v1",
        "format_notes": [
            "This export is intended for Codex/LLM and reviewer analysis.",
            (
                "Message content, stored tool parameters/results, and stored turn trace JSON are exported "
                "from persistence."
            ),
            "IDs are preserved so findings can be traced back to messages, tool calls, and turn traces.",
        ],
        "export": {
            "title": title,
            "exported_at": bundle.exported_at,
            "exported_by": user_export_payload(bundle.exported_by),
            "access_role": bundle.access_role,
            "source": "octryx",
        },
        "session": _session_payload(bundle.session),
        "counts": {
            "messages": len(bundle.messages),
            "tool_calls": len(bundle.tool_calls),
            "turn_traces": len(bundle.turn_traces),
        },
        "messages": [
            _message_payload(
                message,
                related_tool_calls=tool_calls_by_message_id.get(message.id, []),
                related_turn_traces=traces_by_message_id.get(message.id, []),
            )
            for message in bundle.messages
        ],
        "tool_calls": [_tool_call_payload(tool_call) for tool_call in bundle.tool_calls],
        "turn_traces": [_turn_trace_payload(trace) for trace in bundle.turn_traces],
        "timeline": _timeline_payload(bundle),
    }


def _session_payload(session: Any) -> dict[str, Any]:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "project_id": session.project_id,
        "agent_type": session.agent_type,
        "status": session.status,
        "run_status": session.run_status,
        "started_at": utc_isoformat(session.started_at),
        "ended_at": utc_isoformat(session.ended_at),
        "parent_session_id": session.parent_session_id,
        "sub_agent_depth": session.sub_agent_depth,
        "recovery_policy": session.recovery_policy,
        "flow_definition_version_id": session.flow_definition_version_id,
        "flow_node_id": session.flow_node_id,
        "metadata": session.metadata_ or {},
    }


def _message_payload(
    message: Message,
    *,
    related_tool_calls: list[ToolCall],
    related_turn_traces: list[TurnTrace],
) -> dict[str, Any]:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content or "",
        "model": message.model,
        "tokens_in": message.tokens_in or 0,
        "tokens_out": message.tokens_out or 0,
        "cost": float(message.cost or 0),
        "created_at": utc_isoformat(message.created_at),
        "message_tool_calls": message.tool_calls,
        "message_tool_results": message.tool_results,
        "tool_call_ids": [tool_call.id for tool_call in related_tool_calls],
        "turn_trace_ids": [trace.id for trace in related_turn_traces],
    }


def _tool_call_payload(tool_call: ToolCall) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "session_id": tool_call.session_id,
        "message_id": tool_call.message_id,
        "tool_name": tool_call.tool_name,
        "parameters": tool_call.parameters or {},
        "result": tool_call.result,
        "status": tool_call.status,
        "duration_ms": tool_call.duration_ms,
        "request_id": tool_call.request_id,
        "created_at": utc_isoformat(tool_call.created_at),
    }


def _turn_trace_payload(trace: TurnTrace) -> dict[str, Any]:
    return {
        "id": trace.id,
        "session_id": trace.session_id,
        "message_id": trace.message_id,
        "provider": trace.provider,
        "model": trace.model,
        "input_messages": trace.input_messages_json if isinstance(trace.input_messages_json, list) else [],
        "context_snapshot": trace.context_snapshot_json if isinstance(trace.context_snapshot_json, dict) else {},
        "tool_trace": trace.tool_trace_json if isinstance(trace.tool_trace_json, list) else [],
        "raw_output": trace.raw_output,
        "usage": trace.usage_json if isinstance(trace.usage_json, dict) else {},
        "created_at": utc_isoformat(trace.created_at),
    }


def _timeline_payload(bundle: SessionExportBundle) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in bundle.messages:
        items.append(
            {
                "kind": "message",
                "id": message.id,
                "message_id": message.id,
                "role": message.role,
                "created_at": utc_isoformat(message.created_at),
            }
        )
    for tool_call in bundle.tool_calls:
        items.append(
            {
                "kind": "tool_call",
                "id": tool_call.id,
                "message_id": tool_call.message_id,
                "tool_name": tool_call.tool_name,
                "status": tool_call.status,
                "created_at": utc_isoformat(tool_call.created_at),
            }
        )
    for trace in bundle.turn_traces:
        items.append(
            {
                "kind": "turn_trace",
                "id": trace.id,
                "message_id": trace.message_id,
                "provider": trace.provider,
                "model": trace.model,
                "created_at": utc_isoformat(trace.created_at),
            }
        )
    return sorted(items, key=lambda item: str(item.get("created_at") or ""))
