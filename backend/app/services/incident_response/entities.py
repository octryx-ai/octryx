"""Kill switch on single entities: pause, resume, and cancel their running runs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ValidationError
from app.exceptions.base import NotFoundError

from ...models.agent.agent_chain import AgentChainRun
from ...models.project.task import TaskRun
from ...models.runtime.incident_response import (
    ACTION_CANCEL,
    ACTION_PAUSE,
    ACTION_RESUME,
    ALL_TARGET_TYPES,
    TARGET_AGENT_CHAIN,
    TARGET_TASK,
    KillSwitchLog,
    PausedEntity,
)
from ...time_utils import utc_now
from .sweep import _TARGET_MODEL_MAP


async def _entity_or_404(db: AsyncSession, target_type: str, target_id: str) -> Any:
    model_cls = _TARGET_MODEL_MAP[target_type]
    entity = (await db.execute(select(model_cls).where(model_cls.id == target_id))).scalar_one_or_none()
    if not entity:
        raise NotFoundError(target_type, target_id)
    return entity


async def _open_pause(db: AsyncSession, target_type: str, target_id: str) -> PausedEntity | None:
    """The entity's pause record that has not been resumed yet, if any."""
    return (
        await db.execute(
            select(PausedEntity).where(
                PausedEntity.entity_type == target_type,
                PausedEntity.entity_id == target_id,
                PausedEntity.resumed_at.is_(None),
            )
        )
    ).scalar_one_or_none()


def _pause_record(
    *,
    target_type: str,
    target_id: str,
    project_id: str | None,
    previous_is_active: Any,
    log_id: str,
    incident_id: str | None,
    reason: str | None,
) -> PausedEntity:
    return PausedEntity(
        id=str(uuid.uuid4()),
        entity_type=target_type,
        entity_id=target_id,
        project_id=project_id,
        previous_is_active=previous_is_active,
        paused_by_kill_switch_id=log_id,
        incident_id=incident_id,
        reason=reason,
    )


def _require_pausable(target_type: str) -> None:
    if target_type not in ALL_TARGET_TYPES:
        raise ValidationError(f"Invalid target_type: {target_type}")
    if target_type not in _TARGET_MODEL_MAP:
        raise ValidationError(f"Pause not supported for target_type: {target_type}")


async def pause_entity(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    user_id: str,
    reason: str | None = None,
    incident_id: str | None = None,
) -> dict[str, Any]:
    """Pause a specific entity (flow, agent_chain, task, scheduler, domain_pack).

    Sets is_active=False and records in paused_entities for later resume.
    """
    _require_pausable(target_type)
    entity = await _entity_or_404(db, target_type, target_id)
    previous_is_active = getattr(entity, "is_active", True)
    project_id = getattr(entity, "project_id", None)

    # Already paused? Check paused_entities table
    existing = await _open_pause(db, target_type, target_id)
    if existing:
        return {"status": "already_paused", "paused_entity_id": existing.id}

    # Set is_active = False
    entity.is_active = False

    # Record audit log
    log = KillSwitchLog(
        id=str(uuid.uuid4()),
        action=ACTION_PAUSE,
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        user_id=user_id,
        reason=reason,
        incident_id=incident_id,
    )
    db.add(log)

    # Track paused entity for later resume
    paused = _pause_record(
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        previous_is_active=previous_is_active,
        log_id=log.id,
        incident_id=incident_id,
        reason=reason,
    )
    db.add(paused)

    await db.commit()
    return {
        "status": "paused",
        "target_type": target_type,
        "target_id": target_id,
        "paused_entity_id": paused.id,
        "kill_switch_log_id": log.id,
    }


async def resume_entity(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Resume a previously paused entity."""
    if target_type not in _TARGET_MODEL_MAP:
        raise ValidationError(f"Resume not supported for target_type: {target_type}")

    entity = await _entity_or_404(db, target_type, target_id)

    paused = await _open_pause(db, target_type, target_id)

    # Restore is_active
    restore_to = paused.previous_is_active if paused else True
    entity.is_active = restore_to

    if paused:
        paused.resumed_at = utc_now()

    log = KillSwitchLog(
        id=str(uuid.uuid4()),
        action=ACTION_RESUME,
        target_type=target_type,
        target_id=target_id,
        project_id=getattr(entity, "project_id", None),
        user_id=user_id,
        details={"restored_is_active": restore_to},
    )
    db.add(log)
    await db.commit()

    return {
        "status": "resumed",
        "target_type": target_type,
        "target_id": target_id,
        "restored_is_active": restore_to,
        "kill_switch_log_id": log.id,
    }


async def cancel_running_runs(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    user_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel all in-progress runs for a specific entity."""
    cancelled = 0
    if target_type == TARGET_AGENT_CHAIN:
        result = await db.execute(
            update(AgentChainRun)
            .where(AgentChainRun.template_id == target_id, AgentChainRun.status == "in_progress")
            .values(status="cancelled")
        )
        cancelled = result.rowcount
    elif target_type == TARGET_TASK:
        result = await db.execute(
            update(TaskRun)
            .where(TaskRun.task_id == target_id, TaskRun.status == "in_progress")
            .values(status="cancelled")
        )
        cancelled = result.rowcount

    log = KillSwitchLog(
        id=str(uuid.uuid4()),
        action=ACTION_CANCEL,
        target_type=target_type,
        target_id=target_id,
        user_id=user_id,
        reason=reason,
        details={"cancelled_count": cancelled},
    )
    db.add(log)
    await db.commit()

    return {
        "status": "cancelled",
        "target_type": target_type,
        "target_id": target_id,
        "cancelled_runs": cancelled,
        "kill_switch_log_id": log.id,
    }
