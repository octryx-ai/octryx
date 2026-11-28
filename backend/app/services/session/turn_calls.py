"""The model calls behind one chat answer, for the chat's trace view."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, TurnTrace
from ...models import Session as AgentSession
from ..devices.run_trace import DEVICE_PROVIDER, GATEWAY_JOB_KEY, GATEWAY_TURN_KEY


def _number(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return 0


def call_row(trace_id: str, provider: str | None, model: str | None, usage: Any, created_at: datetime | None) -> dict:
    usage = usage if isinstance(usage, dict) else {}
    duration = usage.get("duration_ms")
    return {
        "id": trace_id,
        "provider": provider or "",
        "model": model or "",
        "createdAt": created_at.isoformat() if created_at else None,
        "tokens": {
            "input": _number(usage, "input_tokens", "prompt_tokens"),
            "output": _number(usage, "output_tokens", "completion_tokens"),
            "cacheRead": _number(usage, "cache_read_input_tokens"),
            "cacheCreation": _number(usage, "cache_creation_input_tokens"),
        },
        "durationMs": int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
        "stopReason": str(usage.get("stop_reason") or ""),
    }


async def _rows(
    db: AsyncSession, session_ids: str | list[str], after: datetime | None, until: datetime, *,
    answer_id: str | None = None,
) -> list[dict]:
    ids = [session_ids] if isinstance(session_ids, str) else session_ids
    query = select(TurnTrace.id, TurnTrace.provider, TurnTrace.model, TurnTrace.usage_json, TurnTrace.created_at).where(
        TurnTrace.session_id.in_(ids), TurnTrace.created_at <= until
    )
    if after is not None:
        query = query.where(TurnTrace.created_at > after)
    if answer_id is not None:
        # A row linked to another answer is that answer's (the in-app loop writes the answer before its trace).
        query = query.where(or_(TurnTrace.message_id.is_(None), TurnTrace.message_id == answer_id))
    rows = (await db.execute(query.order_by(TurnTrace.created_at, TurnTrace.id))).all()
    return [call_row(*row) for row in rows]


def _context(trace: TurnTrace) -> dict[str, Any]:
    return trace.context_snapshot_json if isinstance(trace.context_snapshot_json, dict) else {}


async def _turn_gateway_sessions(db: AsyncSession, trace: TurnTrace, user_id: str) -> list[str]:
    context = _context(trace)
    job_id, turn_id = str(context.get("job_id") or ""), str(context.get("turn_id") or "")
    if not job_id or not turn_id:
        return []
    return list((await db.execute(select(AgentSession.id).where(
        AgentSession.user_id == user_id,
        AgentSession.metadata_[GATEWAY_JOB_KEY].as_string() == job_id,
        AgentSession.metadata_[GATEWAY_TURN_KEY].as_string() == turn_id,
    ))).scalars())


async def turn_calls(db: AsyncSession, trace: TurnTrace, *, user_id: str) -> dict[str, Any]:
    if trace.created_at is None:
        return {"calls": [], "promptOnDevice": False}
    if trace.provider == DEVICE_PROVIDER:
        turn_sessions = await _turn_gateway_sessions(db, trace, user_id)
        calls = await _rows(db, turn_sessions, None, trace.created_at) if turn_sessions else []
        return {"calls": calls, "promptOnDevice": not calls}
    if not trace.message_id:
        return {"calls": [], "promptOnDevice": False}
    answered_at = (
        await db.execute(select(Message.created_at).where(Message.id == trace.message_id))
    ).scalar_one_or_none()
    previous_answer = None
    if answered_at is not None:
        previous_answer = (
            await db.execute(
                select(func.max(Message.created_at)).where(
                    Message.session_id == trace.session_id,
                    Message.role == "assistant",
                    Message.created_at < answered_at,
                    Message.id != trace.message_id,
                )
            )
        ).scalar_one_or_none()
    calls = await _rows(db, trace.session_id, previous_answer, trace.created_at, answer_id=trace.message_id)
    return {"calls": calls, "promptOnDevice": False}


__all__ = ["call_row", "turn_calls"]
