"""Observability → Runs → run drawer (O1)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution_profile_trace import TRACE_EXECUTION_PROFILE_KEY

from ...models import AuditLog, Project, Session, ToolCall, TurnTrace, TurnTraceSummary, UsageEvent, User
from ...time_utils import ensure_utc
from ..redaction_policy import redact_secret_payload
from .cost_states import cost_state_expression, run_cost_state
from .run_summary import source_for_origin

MAX_STEPS = 200
MAX_TOOLS = 300
CONTENT_VIEWED_ACTION = "observability.run.content_viewed"


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _tokens(usage: Any) -> tuple[int, int]:
    usage = usage if isinstance(usage, Mapping) else {}

    def first(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        return 0

    return (
        first("input_tokens", "prompt_tokens", "inputTokens"),
        first("output_tokens", "completion_tokens", "outputTokens"),
    )


def _gate(raw: Any) -> dict[str, str] | None:
    gate = raw.get("gate_outcome") if isinstance(raw, Mapping) else None
    if not isinstance(gate, Mapping) or not str(gate.get("gate") or "").strip():
        return None
    return {key: str(gate.get(key) or "")[:300] for key in ("gate", "label", "status", "reason")}


async def _rows(db: AsyncSession, run_key: str) -> list[tuple[TurnTrace, TurnTraceSummary]]:
    return [tuple(row) for row in (await db.execute(
        select(TurnTrace, TurnTraceSummary)
        .join(TurnTraceSummary, TurnTraceSummary.trace_id == TurnTrace.id)
        .where(TurnTraceSummary.run_key == run_key)
        .order_by(TurnTraceSummary.created_at, TurnTrace.id)
        .limit(MAX_STEPS)
    )).all()]


async def _in_private_workspace(db: AsyncSession, session_id: str | None) -> bool:
    session = await db.get(Session, session_id) if session_id else None
    project = await db.get(Project, session.project_id) if session is not None and session.project_id else None
    return bool(project is not None and project.access_mode == "private")


async def get_run_detail(db: AsyncSession, run_key: str) -> dict[str, Any] | None:
    pairs = await _rows(db, run_key)
    if not pairs or await _in_private_workspace(db, pairs[-1][0].session_id):
        return None
    rows = [trace for trace, _summary in pairs]
    summaries = [summary for _trace, summary in pairs]
    first, last = rows[0], rows[-1]
    session = await db.get(Session, last.session_id)
    started = min((item.started_at for item in summaries if item.started_at is not None), default=None)
    steps = []
    for row, summary in pairs:
        tokens_in, tokens_out = _tokens(row.usage_json)
        steps.append({
            "time": _iso(row.created_at),
            "kind": "gate" if _gate(row.raw_output) else "model",
            "provider": row.provider or "",
            "model": row.model or "",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "outcome": summary.outcome,
            "gate": _gate(row.raw_output),
        })
    project = await db.get(Project, session.project_id) if session is not None and session.project_id else None
    user = await db.get(User, session.user_id) if session is not None else None
    snapshot = last.context_snapshot_json if isinstance(last.context_snapshot_json, Mapping) else {}
    profile = snapshot.get(TRACE_EXECUTION_PROFILE_KEY)
    return {
        "run_key": run_key,
        "session_id": last.session_id,
        "source": source_for_origin(session.origin if session else None),
        "workspace_id": session.project_id if session else None,
        "user_id": session.user_id if session else None,
        "workspace_name": project.name if project else None,
        "user_name": (user.display_name or user.username) if user else None,
        "agent_label": next((item.agent_label for item in reversed(summaries) if item.agent_label), None),
        "outcome": summaries[-1].outcome,
        "started_at": _iso(started),
        "ended_at": _iso(last.created_at),
        "first_step_at": _iso(first.created_at),
        "steps": steps,
        "steps_truncated": len(rows) >= MAX_STEPS,
        "tools": await _tools(db, run_key, last.session_id, first.created_at),
        "cost": await _cost(db, run_key, last.session_id, first.created_at),
        "effective_setup": dict(profile) if isinstance(profile, Mapping) else None,
    }


def _run_filter(model: Any, run_key: str, session_id: str, since: Any):
    if run_key.startswith("req:"):
        return [model.request_id == run_key[4:]]
    if run_key.startswith("gw:"):
        return [model.session_id == session_id, model.created_at >= since]
    return None


async def _tools(db: AsyncSession, run_key: str, session_id: str, since: Any) -> list[dict[str, Any]]:
    conditions = _run_filter(ToolCall, run_key, session_id, since)
    if conditions is None:
        return []
    rows = (await db.execute(
        select(ToolCall.tool_name, ToolCall.status, ToolCall.duration_ms, ToolCall.created_at)
        .where(*conditions).order_by(ToolCall.created_at).limit(MAX_TOOLS)
    )).all()
    return [{"tool": name, "status": status or "", "duration_ms": duration, "time": _iso(created)}
            for name, status, duration, created in rows]


async def _cost(db: AsyncSession, run_key: str, session_id: str, since: Any) -> dict[str, Any]:
    conditions = _run_filter(UsageEvent, run_key, session_id, since)
    if conditions is None:
        return {"total": None, "state": "not_billed", "by_model": []}
    state = cost_state_expression()
    rows = (await db.execute(
        select(UsageEvent.model, state, func.count(UsageEvent.id), func.coalesce(func.sum(UsageEvent.cost), 0))
        .where(*conditions).group_by(UsageEvent.model, state)
    )).all()
    by_model = [{"model": model or "", "state": row_state, "calls": int(calls), "cost": round(float(cost or 0), 6)}
                for model, row_state, calls, cost in rows]
    return {
        "total": round(sum(item["cost"] for item in by_model), 6),
        "state": run_cost_state({item["state"] for item in by_model}),
        "by_model": by_model,
    }


async def read_run_content(db: AsyncSession, run_key: str, *, viewer_id: str, ip_address: str | None) -> dict | None:
    pairs = await _rows(db, run_key)
    if not pairs or await _in_private_workspace(db, pairs[-1][0].session_id):
        return None
    last = pairs[-1][0]
    db.add(AuditLog(
        user_id=viewer_id, session_id=last.session_id, action=CONTENT_VIEWED_ACTION, resource_type="run",
        resource_id=run_key[:200], details={"trace_id": last.id}, ip_address=(ip_address or "")[:50] or None,
    ))
    await db.commit()
    return {
        "run_key": run_key,
        "trace_id": last.id,
        "input_messages": redact_secret_payload(last.input_messages_json or []),
        "output": redact_secret_payload(last.raw_output or {}),
    }
