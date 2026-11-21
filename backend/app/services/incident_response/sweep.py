"""Scope-wide sweeps of the kill switch: cancel running work, resume paused entities."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from ...models.agent.agent_chain import AgentChainRun, AgentChainTemplate
from ...models.project.scheduler import Scheduler
from ...models.project.task import Task, TaskRun
from ...models.runtime.flow_definition import FlowDefinition
from ...models.runtime.incident_response import (
    TARGET_AGENT_CHAIN,
    TARGET_FLOW,
    TARGET_SCHEDULER,
    TARGET_TASK,
    PausedEntity,
)
from ...time_utils import utc_now

# ── Model lookup for target types ───────────────────────────────────────────

_TARGET_MODEL_MAP = {
    TARGET_FLOW: FlowDefinition,
    TARGET_AGENT_CHAIN: AgentChainTemplate,
    TARGET_TASK: Task,
    TARGET_SCHEDULER: Scheduler,
}


async def _cancel_running_work(
    db: AsyncSession,
    *,
    project_id: str | None,
    incident_id: str | None,
) -> int:
    """Cancel all in-progress runs within scope."""
    total = 0

    # Cancel agent chain runs
    stmt = update(AgentChainRun).where(AgentChainRun.status == "in_progress")
    if project_id:
        stmt = stmt.where(AgentChainRun.project_id == project_id)
    stmt = stmt.values(status="cancelled")
    result = await db.execute(stmt)
    total += result.rowcount

    # Cancel task runs (no direct project_id column, so we join via Task)
    if project_id:
        # Get task IDs in project
        task_ids_stmt = select(Task.id).where(Task.project_id == project_id)
        task_ids = (await db.execute(task_ids_stmt)).scalars().all()
        if task_ids:
            stmt = (
                update(TaskRun)
                .where(TaskRun.status == "in_progress", TaskRun.task_id.in_(task_ids))
                .values(status="cancelled")
            )
            result = await db.execute(stmt)
            total += result.rowcount
    else:
        stmt = update(TaskRun).where(TaskRun.status == "in_progress").values(status="cancelled")
        result = await db.execute(stmt)
        total += result.rowcount

    # Update session run_status
    stmt = update(Session).where(Session.run_status == "in_progress")
    if project_id:
        stmt = stmt.where(Session.project_id == project_id)
    stmt = stmt.values(run_status="cancelled")
    result = await db.execute(stmt)
    total += result.rowcount

    return total


async def _resume_paused_entities(
    db: AsyncSession,
    *,
    project_id: str | None,
    incident_id: str | None,
) -> int:
    """Resume all entities paused by the given incident."""
    stmt = select(PausedEntity).where(PausedEntity.resumed_at.is_(None))
    if project_id:
        stmt = stmt.where(PausedEntity.project_id == project_id)
    if incident_id:
        stmt = stmt.where(PausedEntity.incident_id == incident_id)

    paused_list = (await db.execute(stmt)).scalars().all()
    count = 0
    now = utc_now()

    for paused in paused_list:
        if paused.entity_type not in _TARGET_MODEL_MAP:
            continue
        model_cls = _TARGET_MODEL_MAP[paused.entity_type]
        entity = (await db.execute(select(model_cls).where(model_cls.id == paused.entity_id))).scalar_one_or_none()
        if entity:
            entity.is_active = paused.previous_is_active if paused.previous_is_active is not None else True
            paused.resumed_at = now
            count += 1

    return count
