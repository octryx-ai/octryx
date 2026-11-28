"""Run summary fields written on every ``turn_traces`` row."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from ...time_utils import utc_now

OUTCOME_COMPLETED = "completed"
OUTCOME_FAILED = "failed"
OUTCOME_BLOCKED = "blocked"
OUTCOME_NEEDS_APPROVAL = "needs_approval"
OUTCOME_NEEDS_CLARIFICATION = "needs_clarification"
RUN_OUTCOMES = (
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_BLOCKED,
    OUTCOME_NEEDS_APPROVAL,
    OUTCOME_NEEDS_CLARIFICATION,
)

# Run source, derived from ``sessions.origin`` (the session's creator) at read time.
SOURCE_CHAT = "chat"
SOURCE_GATEWAY = "gateway"
SOURCE_DEVICE = "device"
SOURCE_WORKFLOW = "workflow"
RUN_SOURCES = (SOURCE_CHAT, SOURCE_GATEWAY, SOURCE_DEVICE, SOURCE_WORKFLOW)
ORIGINS_BY_SOURCE: dict[str, tuple[str, ...]] = {
    SOURCE_CHAT: ("chat", "channel"),
    SOURCE_GATEWAY: ("model_gateway", "mcp"),
    SOURCE_DEVICE: ("device_chat",),
    SOURCE_WORKFLOW: (
        "scheduler", "worker", "flow", "sub_agent", "work_item_analysis", "webhook",
        "control_plane_test",
    ),
}

_GATE_STATUS_OUTCOMES = {
    "needs_approval": OUTCOME_NEEDS_APPROVAL,
    "needs_clarification": OUTCOME_NEEDS_CLARIFICATION,
}
_LOOP_STATUS_OUTCOMES = {
    "waiting_approval": OUTCOME_NEEDS_APPROVAL,
    "needs_approval": OUTCOME_NEEDS_APPROVAL,
    "needs_clarification": OUTCOME_NEEDS_CLARIFICATION,
    "waiting_clarification": OUTCOME_NEEDS_CLARIFICATION,
    "denied": OUTCOME_BLOCKED,
    "blocked": OUTCOME_BLOCKED,
    "failed": OUTCOME_FAILED,
    "error": OUTCOME_FAILED,
}
RUN_KEY_MAX = 120
AGENT_LABEL_MAX = 200


def source_for_origin(origin: str | None) -> str:
    for source, origins in ORIGINS_BY_SOURCE.items():
        if (origin or "chat") in origins:
            return source
    return SOURCE_WORKFLOW


def turn_outcome(raw_output: Any, usage: Any = None) -> str:
    raw = raw_output if isinstance(raw_output, Mapping) else {}
    meta = usage if isinstance(usage, Mapping) else {}
    gate = raw.get("gate_outcome")
    if isinstance(gate, Mapping) and str(gate.get("gate") or "").strip():
        return _GATE_STATUS_OUTCOMES.get(str(gate.get("status") or "").strip(), OUTCOME_BLOCKED)
    status = str(raw.get("status") or "").strip()
    if status in _LOOP_STATUS_OUTCOMES:
        return _LOOP_STATUS_OUTCOMES[status]
    if meta.get("refused_reason") or raw.get("refusal_reason"):
        return OUTCOME_BLOCKED
    if raw.get("error") or meta.get("upstream_error_type"):
        return OUTCOME_FAILED
    upstream_status = meta.get("upstream_status")
    if isinstance(upstream_status, int) and upstream_status >= 400:
        return OUTCOME_FAILED
    return OUTCOME_COMPLETED


def in_app_run_key(request_id: str | None, trace_id: str) -> str:
    request_id = str(request_id or "").strip()
    return (f"req:{request_id}" if request_id else f"trace:{trace_id}")[:RUN_KEY_MAX]


def gateway_run_key(session_id: str) -> str:
    return f"gw:{session_id}"[:RUN_KEY_MAX]


def device_run_key(job_id: str, turn_id: str | None) -> str:
    return f"dev:{job_id}:{turn_id or ''}"[:RUN_KEY_MAX]


def agent_label(context_snapshot: Any) -> str | None:
    snapshot = context_snapshot if isinstance(context_snapshot, Mapping) else {}
    agent = snapshot.get("agent")
    name = str(agent.get("name") or "").strip() if isinstance(agent, Mapping) else ""
    return name[:AGENT_LABEL_MAX] or None


def run_summary_fields(
    *,
    run_key: str,
    raw_output: Any,
    usage: Any = None,
    started_at: datetime | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    return {
        "run_key": run_key[:RUN_KEY_MAX],
        "outcome": turn_outcome(raw_output, usage),
        "started_at": started_at,
        "agent_label": (label or "").strip()[:AGENT_LABEL_MAX] or None,
    }


def summary_row(trace: Any, fields: dict[str, Any]) -> Any:
    from ...models import TurnTraceSummary

    return TurnTraceSummary(
        trace_id=trace.id, session_id=trace.session_id, provider=(trace.provider or "")[:100] or None,
        model=(trace.model or "")[:100] or None, created_at=trace.created_at or utc_now(), **fields,
    )


def gateway_run_summary(
    *,
    session_id: str,
    raw_output: Any,
    usage: Any,
    duration_ms: int | None,
    client_context: Mapping[str, str] | None,
    seat: bool = False,
) -> dict[str, Any]:
    measured = isinstance(duration_ms, int) and duration_ms >= 0
    started = utc_now() - timedelta(milliseconds=duration_ms) if measured else None
    client = "Claude Code" if (client_context or {}).get("claude_session_id") else "Model gateway"
    return run_summary_fields(
        run_key=gateway_run_key(session_id),
        raw_output=raw_output,
        usage=usage,
        started_at=started,
        label=f"{client} ({'seat' if seat else 'gateway'})" if client == "Claude Code" else client,
    )


__all__ = [
    "ORIGINS_BY_SOURCE",
    "OUTCOME_BLOCKED",
    "OUTCOME_COMPLETED",
    "OUTCOME_FAILED",
    "OUTCOME_NEEDS_APPROVAL",
    "OUTCOME_NEEDS_CLARIFICATION",
    "RUN_OUTCOMES",
    "RUN_SOURCES",
    "agent_label",
    "device_run_key",
    "gateway_run_key",
    "gateway_run_summary",
    "in_app_run_key",
    "run_summary_fields",
    "summary_row",
    "source_for_origin",
    "turn_outcome",
]
