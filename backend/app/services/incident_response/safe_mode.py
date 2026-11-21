"""Safe mode: switch it on or off (global or per project) and check whether it blocks new runs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ValidationError

from ...models.runtime.incident_response import (
    ACTION_SAFE_MODE_OFF,
    ACTION_SAFE_MODE_ON,
    SAFE_MODE_ACTIVE,
    SAFE_MODE_OFF,
    TARGET_GLOBAL,
    TARGET_PROJECT,
    KillSwitchLog,
    SafeModeState,
)
from ...time_utils import utc_now
from .sweep import _cancel_running_work, _resume_paused_entities


async def get_safe_mode_status(
    db: AsyncSession,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Get current safe mode status (global or project-scoped)."""
    stmt = select(SafeModeState).where(SafeModeState.project_id == project_id)
    state = (await db.execute(stmt)).scalar_one_or_none()
    if not state:
        return {
            "state": SAFE_MODE_OFF,
            "project_id": project_id,
            "reason": None,
            "incident_id": None,
            "activated_at": None,
            "activated_by": None,
        }
    return {
        "id": state.id,
        "state": state.state,
        "project_id": state.project_id,
        "reason": state.reason,
        "incident_id": state.incident_id,
        "activated_at": state.activated_at.isoformat() if state.activated_at else None,
        "activated_by": state.activated_by,
        "cancel_running_work": state.cancel_running_work,
        "block_new_runs": state.block_new_runs,
        "notify_users": state.notify_users,
    }


def _mark_active(
    state: SafeModeState,
    *,
    user_id: str,
    reason: str,
    incident_id: str | None,
    now: Any,
    cancel_running_work: bool,
    block_new_runs: bool,
    notify_users: bool,
) -> None:
    state.state = SAFE_MODE_ACTIVE
    state.reason = reason
    state.incident_id = incident_id
    state.activated_by = user_id
    state.activated_at = now
    state.deactivated_by = None
    state.deactivated_at = None
    state.cancel_running_work = cancel_running_work
    state.block_new_runs = block_new_runs
    state.notify_users = notify_users


async def _activatable_state(db: AsyncSession, project_id: str | None) -> SafeModeState:
    """The scope's safe mode row, new if there is none; refused when safe mode is already on."""
    stmt = select(SafeModeState).where(SafeModeState.project_id == project_id)
    state = (await db.execute(stmt)).scalar_one_or_none()

    if state and state.state == SAFE_MODE_ACTIVE:
        raise ValidationError(f"Safe mode is already active (id={state.id})")

    if not state:
        state = SafeModeState(
            id=str(uuid.uuid4()),
            project_id=project_id,
        )
        db.add(state)
    return state


def _safe_mode_on_log(
    *,
    project_id: str | None,
    user_id: str,
    reason: str,
    incident_id: str | None,
    cancel_running_work: bool,
    block_new_runs: bool,
) -> KillSwitchLog:
    return KillSwitchLog(
        id=str(uuid.uuid4()),
        action=ACTION_SAFE_MODE_ON,
        target_type=TARGET_PROJECT if project_id else TARGET_GLOBAL,
        target_id=project_id,
        project_id=project_id,
        user_id=user_id,
        reason=reason,
        incident_id=incident_id,
        details={
            "cancel_running_work": cancel_running_work,
            "block_new_runs": block_new_runs,
        },
    )


async def activate_safe_mode(
    db: AsyncSession,
    *,
    user_id: str,
    reason: str,
    project_id: str | None = None,
    incident_id: str | None = None,
    cancel_running_work: bool = False,
    block_new_runs: bool = True,
    notify_users: bool = True,
) -> dict[str, Any]:
    """Activate safe mode (global or project-scoped).

    If cancel_running_work is True, cancels all in-progress runs in scope.
    """
    now = utc_now()
    state = await _activatable_state(db, project_id)

    _mark_active(
        state,
        user_id=user_id,
        reason=reason,
        incident_id=incident_id,
        now=now,
        cancel_running_work=cancel_running_work,
        block_new_runs=block_new_runs,
        notify_users=notify_users,
    )

    # Audit log
    log = _safe_mode_on_log(
        project_id=project_id,
        user_id=user_id,
        reason=reason,
        incident_id=incident_id,
        cancel_running_work=cancel_running_work,
        block_new_runs=block_new_runs,
    )
    db.add(log)

    cancelled_count = 0
    if cancel_running_work:
        cancelled_count = await _cancel_running_work(db, project_id=project_id, incident_id=incident_id)

    await db.commit()
    await db.refresh(state)

    return {
        **await get_safe_mode_status(db, project_id=project_id),
        "cancelled_runs": cancelled_count,
        "kill_switch_log_id": log.id,
    }


async def deactivate_safe_mode(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str | None = None,
    auto_resume: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    """Deactivate safe mode and optionally resume paused entities; ``reason`` goes into the audit log."""
    now = utc_now()
    stmt = select(SafeModeState).where(SafeModeState.project_id == project_id)
    state = (await db.execute(stmt)).scalar_one_or_none()

    if not state or state.state == SAFE_MODE_OFF:
        raise ValidationError("Safe mode is not active")

    incident_id = state.incident_id
    state.state = SAFE_MODE_OFF
    state.deactivated_by = user_id
    state.deactivated_at = now

    log = KillSwitchLog(
        id=str(uuid.uuid4()),
        action=ACTION_SAFE_MODE_OFF,
        target_type=TARGET_PROJECT if project_id else TARGET_GLOBAL,
        target_id=project_id,
        project_id=project_id,
        user_id=user_id,
        reason=reason,
        incident_id=incident_id,
        details={"auto_resume": auto_resume},
    )
    db.add(log)

    resumed_count = 0
    if auto_resume:
        resumed_count = await _resume_paused_entities(db, project_id=project_id, incident_id=incident_id)

    await db.commit()
    return {
        "state": SAFE_MODE_OFF,
        "deactivated_at": now.isoformat(),
        "deactivated_by": user_id,
        "resumed_entities": resumed_count,
        "kill_switch_log_id": log.id,
    }


async def is_blocked_by_safe_mode(
    db: AsyncSession,
    *,
    project_id: str | None = None,
) -> tuple[bool, str | None]:
    """Check if new runs should be blocked.

    Returns (blocked: bool, reason: str | None).
    """
    # Check global safe mode
    global_status = await get_safe_mode_status(db, project_id=None)
    if global_status["state"] == SAFE_MODE_ACTIVE and global_status.get("block_new_runs", True):
        return True, global_status.get("reason")

    # Check project-scoped safe mode
    if project_id:
        project_status = await get_safe_mode_status(db, project_id=project_id)
        if project_status["state"] == SAFE_MODE_ACTIVE and project_status.get("block_new_runs", True):
            return True, project_status.get("reason")

    return False, None
