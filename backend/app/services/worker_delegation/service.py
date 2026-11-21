from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    AgentWorker,
    Session,
    TaskRun,
    User,
    WorkerDelegation,
    WorkerDomainExpertise,
    WorkerOnboarding,
    WorkerRuntimeState,
)
from ...time_utils import utc_now
from ..worker.admin import get_worker_with_relations as _get_worker_with_relations
from ..worker.admin import require_admin as _require_admin
from ..worker.policy import can_worker_execute_action


async def _get_delegation_with_relations(db: AsyncSession, delegation_id: str) -> WorkerDelegation | None:
    return (
        await db.execute(
            select(WorkerDelegation)
            .options(
                selectinload(WorkerDelegation.from_worker).selectinload(AgentWorker.runtime_state),
                selectinload(WorkerDelegation.to_worker).selectinload(AgentWorker.runtime_state),
                selectinload(WorkerDelegation.to_worker).selectinload(AgentWorker.onboarding),
                selectinload(WorkerDelegation.source_session),
                selectinload(WorkerDelegation.delegated_session),
            )
            .where(WorkerDelegation.id == delegation_id)
        )
    ).scalar_one_or_none()


def _serialize_delegation(row: WorkerDelegation) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "from_worker_id": row.from_worker_id,
        "from_worker_name": row.from_worker.name if row.from_worker else None,
        "to_worker_id": row.to_worker_id,
        "to_worker_name": row.to_worker.name if row.to_worker else None,
        "source_session_id": row.source_session_id,
        "delegated_session_id": row.delegated_session_id,
        "task_run_id": row.task_run_id,
        "required_domain": row.required_domain,
        "priority": int(row.priority or 5),
        "requested_action": row.requested_action,
        "context_summary": row.context_summary,
        "context_payload": row.context_payload or {},
        "auto_selected": bool(row.auto_selected),
        "status": row.status,
        "response_note": row.response_note,
        "completion_summary": row.completion_summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "responded_at": row.responded_at.isoformat() if row.responded_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


async def _list_candidate_workers(
    db: AsyncSession,
    *,
    project_id: str,
    exclude_worker_id: str,
    requested_action: str,
) -> list[AgentWorker]:
    rows = (
        (
            await db.execute(
                select(AgentWorker)
                .options(
                    selectinload(AgentWorker.onboarding),
                    selectinload(AgentWorker.runtime_state),
                )
                .where(
                    AgentWorker.project_id == project_id,
                    AgentWorker.is_active,
                    AgentWorker.id != exclude_worker_id,
                )
            )
        )
        .scalars()
        .all()
    )
    candidates: list[AgentWorker] = []
    for worker in rows:
        onboarding = worker.onboarding or WorkerOnboarding(worker_id=worker.id)
        runtime = worker.runtime_state
        if onboarding.onboarding_status != "ready":
            continue
        if runtime is None or runtime.status != "active":
            continue
        if int(runtime.available_slots or 0) <= 0:
            continue
        if not can_worker_execute_action(worker, onboarding, requested_action):
            continue
        candidates.append(worker)
    return candidates


async def _select_target_worker(
    db: AsyncSession,
    *,
    from_worker: AgentWorker,
    required_domain: str | None,
    requested_action: str,
) -> AgentWorker | None:
    candidates = await _list_candidate_workers(
        db,
        project_id=from_worker.project_id,
        exclude_worker_id=from_worker.id,
        requested_action=requested_action,
    )
    if not candidates:
        return None
    domain = str(required_domain or "").strip().lower()
    expertise_lookup: dict[str, WorkerDomainExpertise] = {}
    if domain:
        expertise_rows = (
            (
                await db.execute(
                    select(WorkerDomainExpertise).where(
                        WorkerDomainExpertise.worker_id.in_([row.id for row in candidates]),
                        WorkerDomainExpertise.domain == domain,
                    )
                )
            )
            .scalars()
            .all()
        )
        expertise_lookup = {row.worker_id: row for row in expertise_rows}

    ranked = sorted(
        candidates,
        key=lambda worker: (
            float(expertise_lookup.get(worker.id).success_rate if expertise_lookup.get(worker.id) else 0.0),
            int(expertise_lookup.get(worker.id).tasks_completed if expertise_lookup.get(worker.id) else 0),
            int(worker.runtime_state.available_slots if worker.runtime_state else 0),
            float(worker.trust_score or 0.0),
            -int(worker.runtime_state.active_tasks_count if worker.runtime_state else 0),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else None


def _delegation_priority_label(priority: int) -> str:
    if priority >= 8:
        return "delegation_high"
    if priority >= 5:
        return "delegation_normal"
    return "delegation_low"


async def list_worker_delegations(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    direction: str = "all",
    status_filter: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    stmt = (
        select(WorkerDelegation)
        .options(
            selectinload(WorkerDelegation.from_worker),
            selectinload(WorkerDelegation.to_worker),
        )
        .order_by(WorkerDelegation.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    direction_key = str(direction or "all").strip().lower()
    if direction_key == "incoming":
        stmt = stmt.where(WorkerDelegation.to_worker_id == worker_id)
    elif direction_key == "outgoing":
        stmt = stmt.where(WorkerDelegation.from_worker_id == worker_id)
    else:
        stmt = stmt.where((WorkerDelegation.from_worker_id == worker_id) | (WorkerDelegation.to_worker_id == worker_id))
    if status_filter:
        stmt = stmt.where(WorkerDelegation.status == str(status_filter).strip().lower())
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize_delegation(row) for row in rows]


async def create_worker_delegation(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    from_worker = await _get_worker_with_relations(db, worker_id)
    if not from_worker:
        raise HTTPException(status_code=404, detail="Source worker not found")

    requested_action = str(payload.get("requested_action") or "diagnose").strip().lower()
    required_domain = str(payload.get("required_domain") or "").strip().lower() or None
    explicit_target_worker_id = str(payload.get("to_worker_id") or "").strip() or None
    auto_selected = False

    if explicit_target_worker_id:
        to_worker = await _get_worker_with_relations(db, explicit_target_worker_id)
        if not to_worker:
            raise HTTPException(status_code=404, detail="Target worker not found")
        if to_worker.project_id != from_worker.project_id:
            raise HTTPException(status_code=400, detail="Delegation target must belong to the same project")
    else:
        to_worker = await _select_target_worker(
            db,
            from_worker=from_worker,
            required_domain=required_domain,
            requested_action=requested_action,
        )
        auto_selected = True
        if to_worker is None:
            raise HTTPException(status_code=409, detail="No eligible target worker available for delegation")

    if to_worker.id == from_worker.id:
        raise HTTPException(status_code=400, detail="Worker cannot delegate to itself")

    onboarding = to_worker.onboarding or WorkerOnboarding(worker_id=to_worker.id)
    runtime = to_worker.runtime_state or WorkerRuntimeState(worker_id=to_worker.id)
    if onboarding.onboarding_status != "ready":
        raise HTTPException(status_code=409, detail="Target worker is not ready")
    if runtime.status != "active" or int(runtime.available_slots or 0) <= 0:
        raise HTTPException(status_code=409, detail="Target worker is currently unavailable")
    if not can_worker_execute_action(to_worker, onboarding, requested_action):
        raise HTTPException(
            status_code=409,
            detail="Target worker is not allowed to perform the requested action",
        )

    source_session_id = (
        str(payload.get("source_session_id") or from_worker.runtime_state.current_session_id or "").strip() or None
    )
    source_session = await db.get(Session, source_session_id) if source_session_id else None
    if source_session and source_session.project_id != from_worker.project_id:
        raise HTTPException(status_code=400, detail="Source session belongs to a different project")

    task_run_id = str(payload.get("task_run_id") or "").strip() or None
    if task_run_id and not await db.get(TaskRun, task_run_id):
        raise HTTPException(status_code=404, detail="Task run not found")

    delegated_session = Session(
        id=str(uuid.uuid4()),
        user_id=source_session.user_id if source_session else current_user.id,
        project_id=from_worker.project_id,
        agent_type=source_session.agent_type if source_session else "diagnosis",
        status="active",
        origin="worker",
        metadata_={
            "title": f"Delegation · {to_worker.name}",
            "trigger": "worker_delegation",
            "from_worker_id": from_worker.id,
            "to_worker_id": to_worker.id,
            "requested_action": requested_action,
            "required_domain": required_domain,
            "context_summary": (payload.get("context_summary") or "").strip() or None,
            "context_payload": payload.get("context_payload") or {},
        },
        parent_session_id=source_session.id if source_session else None,
        sub_agent_depth=(int(source_session.sub_agent_depth or 0) + 1) if source_session else 0,
    )
    db.add(delegated_session)
    await db.flush()

    row = WorkerDelegation(
        id=str(uuid.uuid4()),
        project_id=from_worker.project_id,
        from_worker_id=from_worker.id,
        to_worker_id=to_worker.id,
        source_session_id=source_session.id if source_session else None,
        delegated_session_id=delegated_session.id,
        task_run_id=task_run_id,
        required_domain=required_domain,
        priority=max(0, min(int(payload.get("priority") or 5), 10)),
        requested_action=requested_action,
        context_summary=(payload.get("context_summary") or "").strip() or None,
        context_payload=payload.get("context_payload") or {},
        auto_selected=auto_selected,
        status="pending",
    )
    db.add(row)
    await db.commit()
    reloaded = await _get_delegation_with_relations(db, row.id)
    return _serialize_delegation(reloaded)


async def respond_to_worker_delegation(
    db: AsyncSession,
    *,
    worker_id: str,
    delegation_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    row = await _get_delegation_with_relations(db, delegation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Delegation not found")
    if row.to_worker_id != worker_id:
        raise HTTPException(status_code=403, detail="Only the target worker can respond to this delegation")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="Delegation is no longer pending")

    action = str(payload.get("action") or "").strip().lower()
    if action not in {"accept", "decline"}:
        raise HTTPException(status_code=400, detail="Invalid delegation response")

    row.response_note = (payload.get("response_note") or "").strip() or None
    row.responded_at = utc_now()
    runtime = row.to_worker.runtime_state if row.to_worker else None

    if action == "accept":
        row.status = "accepted"
        if runtime is not None:
            runtime.current_session_id = row.delegated_session_id
            runtime.current_priority = _delegation_priority_label(int(row.priority or 5))
            runtime.last_heartbeat = utc_now()
    else:
        row.status = "declined"
        if row.delegated_session:
            row.delegated_session.status = "cancelled"
            row.delegated_session.ended_at = utc_now()

    await db.commit()
    reloaded = await _get_delegation_with_relations(db, row.id)
    return _serialize_delegation(reloaded)


async def complete_worker_delegation(
    db: AsyncSession,
    *,
    worker_id: str,
    delegation_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    row = await _get_delegation_with_relations(db, delegation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Delegation not found")
    if row.to_worker_id != worker_id:
        raise HTTPException(status_code=403, detail="Only the target worker can complete this delegation")
    if row.status not in {"accepted", "in_progress"}:
        raise HTTPException(status_code=400, detail="Delegation must be accepted before completion")

    completion_status = str(payload.get("status") or "completed").strip().lower()
    if completion_status not in {"completed", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid delegation completion status")

    row.status = completion_status
    row.completion_summary = (payload.get("completion_summary") or "").strip() or None
    row.completed_at = utc_now()

    if row.delegated_session:
        row.delegated_session.status = "completed" if completion_status == "completed" else "error"
        row.delegated_session.ended_at = row.completed_at
        metadata = dict(row.delegated_session.metadata_ or {})
        metadata["delegation_status"] = completion_status
        metadata["completion_summary"] = row.completion_summary
        row.delegated_session.metadata_ = metadata

    if row.to_worker and row.to_worker.runtime_state:
        runtime = row.to_worker.runtime_state
        if runtime.current_session_id == row.delegated_session_id:
            runtime.current_session_id = None
        if int(runtime.active_tasks_count or 0) <= 0:
            runtime.current_priority = "idle"
        runtime.last_heartbeat = utc_now()

    await db.commit()
    reloaded = await _get_delegation_with_relations(db, row.id)
    return _serialize_delegation(reloaded)


__all__ = [
    "_delegation_priority_label",
    "_get_delegation_with_relations",
    "_list_candidate_workers",
    "_select_target_worker",
    "_serialize_delegation",
    "complete_worker_delegation",
    "create_worker_delegation",
    "list_worker_delegations",
    "respond_to_worker_delegation",
]
