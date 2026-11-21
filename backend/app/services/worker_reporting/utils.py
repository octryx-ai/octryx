from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.worker_shift.utils import _local_now

from ...models import (
    AgentWorker,
    Role,
    User,
    UserRole,
    WorkerEscalation,
    WorkerLearning,
    WorkerReport,
    WorkerTrustEvent,
)
from ...time_utils import ensure_utc
from ..admin.governance.admin_access_service import is_global_admin


async def _require_admin(db: AsyncSession, current_user: User) -> None:
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Admin access required")


async def _get_worker(db: AsyncSession, worker_id: str) -> AgentWorker:
    worker = (
        await db.execute(
            select(AgentWorker)
            .options(
                selectinload(AgentWorker.runtime_state),
                selectinload(AgentWorker.onboarding),
                selectinload(AgentWorker.reports),
                selectinload(AgentWorker.learnings),
            )
            .where(AgentWorker.id == worker_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker


def _serialize_report(row: WorkerReport) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "report_type": row.report_type,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "summary": row.summary,
        "incidents_detected": int(row.incidents_detected or 0),
        "incidents_resolved": int(row.incidents_resolved or 0),
        "incidents_escalated": int(row.incidents_escalated or 0),
        "autonomous_actions_taken": int(row.autonomous_actions_taken or 0),
        "knowledge_entries_created": int(row.knowledge_entries_created or 0),
        "memory_updates": int(row.memory_updates or 0),
        "highlights": list(row.highlights or []),
        "concerns": list(row.concerns or []),
        "recommendations": list(row.recommendations or []),
        "delivery_status": row.delivery_status,
        "delivered_to": list(row.delivered_to or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_learning(row: WorkerLearning) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "learning_type": row.learning_type,
        "context": row.context,
        "learning_content": row.learning_content,
        "confidence": float(row.confidence or 0.0),
        "times_applied": int(row.times_applied or 0),
        "times_succeeded": int(row.times_succeeded or 0),
        "source_session_id": row.source_session_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _report_window(worker: AgentWorker) -> tuple[Any, Any]:
    local_now = _local_now(worker)
    end_utc = ensure_utc(local_now)
    if end_utc is None:
        raise ValueError("Unable to determine report window end time")
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = ensure_utc(start_local) or (end_utc - timedelta(days=1))
    return start_utc, end_utc


async def _admin_targets(db: AsyncSession) -> list[User]:
    rows = (
        (
            await db.execute(
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.name == "admin")
                .order_by(User.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _extract_learnings(
    db: AsyncSession,
    *,
    worker: AgentWorker,
    period_start,
    period_end,
) -> list[WorkerLearning]:
    created: list[WorkerLearning] = []
    trust_rows = (
        (
            await db.execute(
                select(WorkerTrustEvent)
                .where(
                    WorkerTrustEvent.worker_id == worker.id,
                    WorkerTrustEvent.created_at >= period_start,
                    WorkerTrustEvent.created_at <= period_end,
                )
                .order_by(WorkerTrustEvent.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    escalation_rows = (
        (
            await db.execute(
                select(WorkerEscalation)
                .where(
                    WorkerEscalation.worker_id == worker.id,
                    WorkerEscalation.created_at >= period_start,
                    WorkerEscalation.created_at <= period_end,
                    WorkerEscalation.was_necessary.is_not(None),
                )
                .order_by(WorkerEscalation.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    for row in trust_rows:
        learning_type = "successful_fix" if row.event_type in {"success", "human_approved"} else "failed_approach"
        confidence = 0.85 if row.event_type in {"success", "human_approved"} else 0.6
        learning = WorkerLearning(
            id=str(uuid.uuid4()),
            worker_id=worker.id,
            learning_type=learning_type,
            context=row.reason,
            learning_content=row.reason or f"Worker trust event {row.event_type}",
            confidence=confidence,
            times_applied=1,
            times_succeeded=1 if row.event_type in {"success", "human_approved"} else 0,
        )
        db.add(learning)
        await db.flush()
        created.append(learning)

    for row in escalation_rows:
        learning_type = "escalation_was_unnecessary" if row.was_necessary is False else "team_feedback"
        learning = WorkerLearning(
            id=str(uuid.uuid4()),
            worker_id=worker.id,
            learning_type=learning_type,
            context=row.context_summary,
            learning_content=row.human_response or row.reason,
            confidence=0.9 if row.was_necessary is False else 0.75,
            times_applied=1,
            times_succeeded=0 if row.was_necessary is False else 1,
            source_session_id=row.session_id,
        )
        db.add(learning)
        await db.flush()
        created.append(learning)
    return created
