"""The coding observability timeline and the trace and tool texts it shows."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from ....models import AuditLog, ToolCall, TurnTrace, UsageEvent, WorkCodingAuditEvent
from ..jira_values import iso

TIMELINE_LIMIT = 160


def _timeline(
    usage_events: list[UsageEvent],
    tool_calls: list[ToolCall],
    turn_traces: list[TurnTrace],
    coding_events: list[WorkCodingAuditEvent],
    audit_logs: list[AuditLog],
) -> list[dict[str, Any]]:
    rows = [
        *(_usage_timeline(row) for row in usage_events),
        *(_tool_timeline(row) for row in tool_calls),
        *(_turn_timeline(row) for row in turn_traces),
        *(_coding_event_timeline(row) for row in coding_events),
        *(_audit_timeline(row) for row in audit_logs),
    ]
    return sorted(rows, key=lambda row: (row.get("created_at") or "", row.get("id") or ""))[-TIMELINE_LIMIT:]


def _usage_timeline(row: UsageEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "llm_call",
        "title": f"{row.provider or 'unknown'} / {row.model or 'unknown'}",
        "status": "recorded",
        "session_id": row.session_id,
        "created_at": iso(row.created_at),
        "summary": f"{int(row.tokens_in or 0) + int(row.tokens_out or 0)} tokens · ${_money(_decimal_cost(row.cost))}",
        "evidence": {
            "tokens_in": int(row.tokens_in or 0),
            "tokens_out": int(row.tokens_out or 0),
            "cost": _money(_decimal_cost(row.cost)),
            "request_id": row.request_id,
            "flow_definition_id": row.flow_definition_id,
            "agent_chain_id": row.agent_chain_id,
        },
    }


def _tool_timeline(row: ToolCall) -> dict[str, Any]:
    result = row.result if isinstance(row.result, dict) else {}
    execution_event = result.get("execution_event") if isinstance(result.get("execution_event"), dict) else {}
    return {
        "id": row.id,
        "kind": "tool_call",
        "title": row.tool_name,
        "status": row.status or "unknown",
        "session_id": row.session_id,
        "created_at": iso(row.created_at),
        "summary": _tool_summary_text(row, execution_event),
        "evidence": {
            "kind": _tool_kind(row),
            "duration_ms": row.duration_ms,
            "request_id": row.request_id,
            "execution_event": _compact_mapping(execution_event),
        },
    }


def _turn_timeline(row: TurnTrace) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "turn_trace",
        "title": f"Turn trace · {row.provider or 'unknown'} / {row.model or 'unknown'}",
        "status": _trace_status(row),
        "session_id": row.session_id,
        "created_at": iso(row.created_at),
        "summary": _trace_summary(row),
        "evidence": {
            "message_id": row.message_id,
            "tool_trace_count": len(row.tool_trace_json or []),
            "stop_reason": _trace_stop_reason(row),
        },
    }


def _coding_event_timeline(row: WorkCodingAuditEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "coding_audit",
        "title": row.title,
        "status": row.event_type,
        "session_id": (row.evidence_json or {}).get("session_id"),
        "created_at": iso(row.created_at),
        "summary": row.summary or "",
        "evidence": {
            "event_type": row.event_type,
            "repository_name": row.repository_name,
            "branch_name": row.branch_name,
            "commit_sha": row.commit_sha,
            "pr_url": row.pr_url,
        },
    }


def _audit_timeline(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "platform_audit",
        "title": row.action,
        "status": "recorded",
        "session_id": row.session_id,
        "created_at": iso(row.created_at),
        "summary": row.resource_type or "",
        "evidence": {
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
        },
    }


def _latest_stop_reason(turn_traces: list[TurnTrace]) -> str | None:
    for row in reversed(turn_traces):
        reason = _trace_stop_reason(row)
        if reason:
            return reason
    return None


def _trace_stop_reason(row: TurnTrace) -> str | None:
    for payload in [row.raw_output, row.usage_json, row.context_snapshot_json]:
        if not isinstance(payload, dict):
            continue
        for key in ("run_completion_reason", "completion_reason", "stop_reason", "finish_reason"):
            value = payload.get(key)
            if value:
                return str(value)
        nested = payload.get("metadata")
        if isinstance(nested, dict):
            for key in ("run_completion_reason", "completion_reason", "stop_reason", "finish_reason"):
                value = nested.get(key)
                if value:
                    return str(value)
    return None


def _trace_status(row: TurnTrace) -> str:
    reason = _trace_stop_reason(row)
    if not reason:
        return "recorded"
    lowered = reason.lower()
    if any(marker in lowered for marker in ("budget", "loop", "blocked", "error", "failed")):
        return "attention"
    return "recorded"


def _trace_summary(row: TurnTrace) -> str:
    usage = row.usage_json if isinstance(row.usage_json, dict) else {}
    token_total = usage.get("total_tokens") or usage.get("tokens_total")
    reason = _trace_stop_reason(row)
    parts = []
    if token_total:
        parts.append(f"{token_total} tokens")
    if reason:
        parts.append(f"stop: {reason}")
    return " · ".join(parts) or "Trace captured"


def _tool_kind(row: ToolCall) -> str:
    name = (row.tool_name or "").lower()
    if any(marker in name for marker in ("write", "edit", "patch", "commit", "pull_request", "pr_create")):
        return "mutation"
    if any(marker in name for marker in ("test", "lint", "validate", "run_cli_command")):
        return "validation"
    if any(marker in name for marker in ("read", "list", "search", "grep", "diff", "status")):
        return "evidence"
    return "tool"


def _tool_summary_text(row: ToolCall, execution_event: dict[str, Any]) -> str:
    parts = []
    if row.duration_ms is not None:
        parts.append(f"{row.duration_ms}ms")
    exit_code = execution_event.get("exit_code")
    if exit_code is not None:
        parts.append(f"exit {exit_code}")
    status = execution_event.get("status") or row.status
    if status:
        parts.append(str(status))
    return " · ".join(parts)


def _compact_mapping(value: dict[str, Any], *, limit: int = 12) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= limit:
            compact["_truncated"] = True
            break
        if isinstance(item, (str, int, float, bool)) or item is None:
            compact[key] = item
        elif isinstance(item, list):
            compact[key] = item[:5]
        elif isinstance(item, dict):
            compact[key] = {nested_key: nested_value for nested_key, nested_value in list(item.items())[:5]}
        else:
            compact[key] = str(item)
    return compact


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _decimal_cost(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _money(value: Decimal) -> str:
    return f"{value:.6f}"
