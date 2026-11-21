from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, ToolCall, TurnTrace, UsageEvent, WorkCodingAuditEvent, WorkItem
from ..jira_values import iso
from .coding_agent_sessions import list_work_item_agent_sessions
from .observability_rows import _audit_logs, _coding_events, _tool_calls, _turn_traces, _usage_events
from .observability_timeline import (
    _compact_mapping,
    _decimal_cost,
    _latest_stop_reason,
    _money,
    _stable_json,
    _timeline,
    _tool_kind,
)


async def get_work_item_coding_observability(db: AsyncSession, work_item_id: str) -> dict[str, Any]:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")

    agent_sessions = await list_work_item_agent_sessions(db, item.id)
    session_ids = [session["id"] for session in agent_sessions if session.get("id")]
    usage_events = await _usage_events(db, session_ids)
    tool_calls = await _tool_calls(db, session_ids)
    turn_traces = await _turn_traces(db, session_ids)
    coding_events = await _coding_events(db, item.id)
    audit_logs = await _audit_logs(db, item.id, session_ids)
    repeated_tools = _repeated_tool_calls(tool_calls)

    summary = {
        "status": _runtime_status(agent_sessions, usage_events, tool_calls, repeated_tools),
        "agent_session_count": len(agent_sessions),
        "llm_call_count": len(usage_events),
        "turn_trace_count": len(turn_traces),
        "tool_call_count": len(tool_calls),
        "failed_tool_call_count": sum(1 for row in tool_calls if (row.status or "").lower() != "success"),
        "coding_audit_event_count": len(coding_events),
        "platform_audit_event_count": len(audit_logs),
        "mutation_event_count": sum(1 for row in tool_calls if _tool_kind(row) == "mutation"),
        "validation_event_count": sum(1 for row in tool_calls if _tool_kind(row) == "validation"),
        "repeated_tool_call_count": sum(entry["count"] for entry in repeated_tools),
        "total_tokens": sum(int(row.tokens_in or 0) + int(row.tokens_out or 0) for row in usage_events),
        "total_cost": _money(sum(_decimal_cost(row.cost) for row in usage_events)),
        "latest_stop_reason": _latest_stop_reason(turn_traces),
        "next_observation": _next_observation(agent_sessions, usage_events, tool_calls, repeated_tools),
    }
    return {
        "schema": "coding_observability.v1",
        "work_item_id": item.id,
        "source_key": item.source_key,
        "generated_from": {
            "agent_sessions": len(agent_sessions),
            "usage_events": len(usage_events),
            "tool_calls": len(tool_calls),
            "turn_traces": len(turn_traces),
            "coding_audit_events": len(coding_events),
            "platform_audit_events": len(audit_logs),
        },
        "summary": summary,
        "agent_sessions": agent_sessions,
        "usage": _usage_summary(usage_events),
        "tools": _tool_summary(tool_calls, repeated_tools),
        "turns": _turn_summary(turn_traces),
        "audit": _audit_summary(coding_events, audit_logs),
        "timeline": _timeline(usage_events, tool_calls, turn_traces, coding_events, audit_logs),
    }


def _usage_summary(events: list[UsageEvent]) -> dict[str, Any]:
    by_model: dict[str, dict[str, Any]] = {}
    by_session: dict[str, dict[str, Any]] = {}
    for event in events:
        model_key = f"{event.provider or 'unknown'} / {event.model or 'unknown'}"
        _add_usage_bucket(by_model, model_key, event)
        _add_usage_bucket(by_session, event.session_id, event)
    total_cost = sum(_decimal_cost(event.cost) for event in events)
    return {
        "total": {
            "events": len(events),
            "tokens_in": sum(int(event.tokens_in or 0) for event in events),
            "tokens_out": sum(int(event.tokens_out or 0) for event in events),
            "tokens_total": sum(int(event.tokens_in or 0) + int(event.tokens_out or 0) for event in events),
            "cost": _money(total_cost),
        },
        "by_model": list(by_model.values()),
        "by_session": list(by_session.values()),
    }


def _add_usage_bucket(target: dict[str, dict[str, Any]], key: str, event: UsageEvent) -> None:
    bucket = target.setdefault(
        key,
        {
            "key": key,
            "provider": event.provider,
            "model": event.model,
            "session_id": event.session_id if key == event.session_id else None,
            "events": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_total": 0,
            "cost": "0.000000",
        },
    )
    bucket["events"] += 1
    bucket["tokens_in"] += int(event.tokens_in or 0)
    bucket["tokens_out"] += int(event.tokens_out or 0)
    bucket["tokens_total"] += int(event.tokens_in or 0) + int(event.tokens_out or 0)
    bucket["cost"] = _money(Decimal(str(bucket["cost"])) + _decimal_cost(event.cost))


def _tool_summary(tool_calls: list[ToolCall], repeated_tools: list[dict[str, Any]]) -> dict[str, Any]:
    by_name: dict[str, dict[str, Any]] = {}
    by_kind = Counter(_tool_kind(row) for row in tool_calls)
    for row in tool_calls:
        bucket = by_name.setdefault(
            row.tool_name,
            {
                "tool_name": row.tool_name,
                "count": 0,
                "success": 0,
                "failed": 0,
                "total_duration_ms": 0,
                "kind": _tool_kind(row),
                "latest_status": row.status or "unknown",
                "latest_at": None,
            },
        )
        bucket["count"] += 1
        if (row.status or "").lower() == "success":
            bucket["success"] += 1
        else:
            bucket["failed"] += 1
        bucket["total_duration_ms"] += int(row.duration_ms or 0)
        bucket["latest_status"] = row.status or "unknown"
        bucket["latest_at"] = iso(row.created_at)
    return {
        "total": len(tool_calls),
        "success": sum(1 for row in tool_calls if (row.status or "").lower() == "success"),
        "failed": sum(1 for row in tool_calls if (row.status or "").lower() != "success"),
        "by_kind": dict(by_kind),
        "by_name": sorted(by_name.values(), key=lambda item: (-int(item["count"]), item["tool_name"])),
        "repeated_calls": repeated_tools,
    }


def _turn_summary(turn_traces: list[TurnTrace]) -> dict[str, Any]:
    by_model = Counter(f"{row.provider or 'unknown'} / {row.model or 'unknown'}" for row in turn_traces)
    return {
        "total": len(turn_traces),
        "latest_stop_reason": _latest_stop_reason(turn_traces),
        "by_model": [{"key": key, "count": count} for key, count in by_model.items()],
    }


def _audit_summary(coding_events: list[WorkCodingAuditEvent], audit_logs: list[AuditLog]) -> dict[str, Any]:
    coding_types = Counter(row.event_type for row in coding_events)
    audit_actions = Counter(row.action for row in audit_logs)
    return {
        "coding_event_count": len(coding_events),
        "platform_event_count": len(audit_logs),
        "coding_events_by_type": dict(coding_types),
        "platform_events_by_action": dict(audit_actions),
    }


def _repeated_tool_calls(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for row in tool_calls:
        key = f"{row.tool_name}:{_stable_json(row.parameters)}"
        entry = counts.setdefault(
            key,
            {
                "tool_name": row.tool_name,
                "count": 0,
                "first_at": iso(row.created_at),
                "latest_at": iso(row.created_at),
                "parameters_preview": _compact_mapping(row.parameters if isinstance(row.parameters, dict) else {}),
            },
        )
        entry["count"] += 1
        entry["latest_at"] = iso(row.created_at)
    return sorted(
        [entry for entry in counts.values() if int(entry["count"]) >= 3],
        key=lambda entry: (-int(entry["count"]), entry["tool_name"]),
    )


def _runtime_status(
    agent_sessions: list[dict[str, Any]],
    usage_events: list[UsageEvent],
    tool_calls: list[ToolCall],
    repeated_tools: list[dict[str, Any]],
) -> str:
    if not agent_sessions:
        return "not_started"
    if repeated_tools:
        return "attention"
    if any((row.status or "").lower() != "success" for row in tool_calls):
        return "attention"
    if not usage_events:
        return "missing_usage"
    return "observed"


def _next_observation(
    agent_sessions: list[dict[str, Any]],
    usage_events: list[UsageEvent],
    tool_calls: list[ToolCall],
    repeated_tools: list[dict[str, Any]],
) -> str:
    if not agent_sessions:
        return "No linked coding agent session exists yet."
    if not usage_events:
        return "The task has an agent session but no LLM usage events; verify runtime accounting."
    if repeated_tools:
        top = repeated_tools[0]
        return f"Repeated {top['tool_name']} calls detected; inspect whether the agent is looping."
    if any((row.status or "").lower() != "success" for row in tool_calls):
        return "One or more tool calls failed; inspect the timeline before continuing."
    if not any(_tool_kind(row) == "mutation" for row in tool_calls):
        return "No code mutation tool call has been recorded yet."
    return "Runtime evidence is captured for this task."
