"""Safe mode: switch it off (global or per project) and check whether it blocks new runs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ValidationError

from ...models.runtime.incident_response import (
    ACTION_SAFE_MODE_OFF,
    SAFE_MODE_ACTIVE,
    SAFE_MODE_OFF,
    TARGET_GLOBAL,
    TARGET_PROJECT,
    KillSwitchLog,
    SafeModeState,
)
from ...time_utils import utc_now


async def get_safe_mode_status(
    db: AsyncSession,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
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


async def deactivate_safe_mode(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
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
    )
    db.add(log)

    await db.commit()
    return {
        "state": SAFE_MODE_OFF,
        "deactivated_at": now.isoformat(),
        "deactivated_by": user_id,
        "kill_switch_log_id": log.id,
    }


async def is_blocked_by_safe_mode(
    db: AsyncSession,
    *,
    project_id: str | None = None,
) -> tuple[bool, str | None]:
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
