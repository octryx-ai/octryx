from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AgentWorker, User, WorkerEscalation, WorkerEscalationRule
from ..worker.admin import require_admin as _require_admin
from ..worker.service import record_worker_trust_event


def _serialize_rule(row: WorkerEscalationRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "trigger_condition": row.trigger_condition,
        "situation_pattern": row.situation_pattern,
        "escalate_to_user_id": row.escalate_to_user_id,
        "escalate_via": row.escalate_via,
        "message_template": row.message_template,
        "priority": row.priority,
        "times_triggered": int(row.times_triggered or 0),
        "times_resolved_after": int(row.times_resolved_after or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_escalation(row: WorkerEscalation) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "rule_id": row.rule_id,
        "session_id": row.session_id,
        "reason": row.reason,
        "context_summary": row.context_summary,
        "escalated_to": row.escalated_to,
        "escalation_channel": row.escalation_channel,
        "human_response": row.human_response,
        "was_necessary": row.was_necessary,
        "resolution_time_minutes": row.resolution_time_minutes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _get_worker(db: AsyncSession, worker_id: str) -> AgentWorker:
    worker = (
        await db.execute(
            select(AgentWorker)
            .options(selectinload(AgentWorker.onboarding), selectinload(AgentWorker.runtime_state))
            .where(AgentWorker.id == worker_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker


async def list_worker_escalation_rules(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    await _get_worker(db, worker_id)
    rows = (
        (
            await db.execute(
                select(WorkerEscalationRule)
                .where(WorkerEscalationRule.worker_id == worker_id)
                .order_by(WorkerEscalationRule.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_rule(row) for row in rows]


async def create_worker_escalation_rule(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    worker = await _get_worker(db, worker_id)
    escalate_to_user_id = payload.get("escalate_to_user_id") or worker.escalation_user_id
    if escalate_to_user_id and not await db.get(User, escalate_to_user_id):
        raise HTTPException(status_code=404, detail="Escalation user not found")
    row = WorkerEscalationRule(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        trigger_condition=str(payload["trigger_condition"]).strip(),
        situation_pattern=(payload.get("situation_pattern") or "").strip() or None,
        escalate_to_user_id=escalate_to_user_id,
        escalate_via=str(payload.get("escalate_via") or "slack").strip(),
        message_template=(payload.get("message_template") or "").strip() or None,
        priority=str(payload.get("priority") or "medium").strip(),
    )
    db.add(row)
    await db.commit()
    return _serialize_rule(row)


async def list_worker_escalations(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    limit: int = 50,
) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    await _get_worker(db, worker_id)
    rows = (
        (
            await db.execute(
                select(WorkerEscalation)
                .where(WorkerEscalation.worker_id == worker_id)
                .order_by(WorkerEscalation.created_at.desc())
                .limit(max(1, min(int(limit), 200)))
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_escalation(row) for row in rows]


async def resolve_escalation_rule(
    db: AsyncSession,
    *,
    worker: AgentWorker,
    reason: str,
    context_summary: str | None = None,
) -> WorkerEscalationRule | None:
    rows = (
        (
            await db.execute(
                select(WorkerEscalationRule)
                .where(WorkerEscalationRule.worker_id == worker.id)
                .order_by(WorkerEscalationRule.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    haystack = f"{reason} {context_summary or ''}".lower()
    for row in rows:
        condition = str(row.trigger_condition or "").strip().lower()
        pattern = str(row.situation_pattern or "").strip().lower()
        if condition and condition in haystack:
            return row
        if pattern and pattern in haystack:
            return row
    return rows[0] if rows else None


async def log_worker_escalation(
    db: AsyncSession,
    *,
    worker: AgentWorker,
    reason: str,
    context_summary: str | None,
    session_id: str | None = None,
    escalation_channel: str | None = None,
) -> dict[str, Any]:
    rule = await resolve_escalation_rule(db, worker=worker, reason=reason, context_summary=context_summary)
    if rule is not None:
        rule.times_triggered = int(rule.times_triggered or 0) + 1
    row = WorkerEscalation(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        rule_id=rule.id if rule else None,
        session_id=session_id,
        reason=reason,
        context_summary=context_summary,
        escalated_to=(rule.escalate_to_user_id if rule and rule.escalate_to_user_id else worker.escalation_user_id),
        escalation_channel=escalation_channel or (rule.escalate_via if rule else None),
    )
    db.add(row)
    await db.flush()
    return _serialize_escalation(row)


async def review_worker_escalation(
    db: AsyncSession,
    *,
    worker_id: str,
    escalation_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    worker = await _get_worker(db, worker_id)
    row = await db.get(WorkerEscalation, escalation_id)
    if row is None or row.worker_id != worker.id:
        raise HTTPException(status_code=404, detail="Worker escalation not found")
    row.human_response = (payload.get("human_response") or "").strip() or None
    row.was_necessary = bool(payload["was_necessary"])
    row.resolution_time_minutes = payload.get("resolution_time_minutes")
    if row.rule_id:
        rule = await db.get(WorkerEscalationRule, row.rule_id)
        if rule and row.was_necessary:
            rule.times_resolved_after = int(rule.times_resolved_after or 0) + 1
    await record_worker_trust_event(
        db,
        worker=worker,
        event_type="correct_escalation" if row.was_necessary else "unnecessary_escalation",
        reason=row.human_response or row.reason,
    )
    await db.commit()
    return _serialize_escalation(row)


__all__ = [
    "create_worker_escalation_rule",
    "list_worker_escalation_rules",
    "list_worker_escalations",
    "log_worker_escalation",
    "resolve_escalation_rule",
    "review_worker_escalation",
]
