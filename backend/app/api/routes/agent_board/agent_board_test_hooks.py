"""A test hook for the handoff live acceptance; off unless ``OCTRYX_ENABLE_TEST_HOOKS=true``."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import AgentPresence, AuditLog, User
from ....services.access_control import _user_is_admin, require_existing_workspace
from ....services.agent_board.automation import request_handoffs_for_presence
from ....services.agent_gateway.presence import STATE_ACTIVE, STATE_LIMIT_REACHED, session_key_hash
from ....services.auth import get_current_user
from ....time_utils import utc_now

router = APIRouter()

TEST_HOOKS_ENV = "OCTRYX_ENABLE_TEST_HOOKS"
AUDIT_ACTION = "agent_board.test.presence_limit"


def test_hooks_enabled() -> bool:
    return str(os.environ.get(TEST_HOOKS_ENV) or "").strip().lower() == "true"


@router.post("/test/presence-limit")
async def set_presence_limit(
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not test_hooks_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    if not await _user_is_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Platform admin required")
    project_id, agent_hash, pct = body.get("project_id"), body.get("agent_hash"), body.get("seven_day_pct")
    await require_existing_workspace(db, current_user.id, project_id if isinstance(project_id, str) else None)
    if not isinstance(project_id, str) or not isinstance(agent_hash, str) or \
            type(pct) not in (int, float) or not 0 <= pct <= 1000:
        raise HTTPException(status_code=422, detail="project_id, agent_hash and seven_day_pct are required")
    sessions = (
        await db.execute(
            select(AgentPresence).where(AgentPresence.project_id == project_id, AgentPresence.stopped_at.is_(None))
        )
    ).scalars().all()
    presence = next((row for row in sessions if session_key_hash(row.session_key) == agent_hash), None)
    if presence is None:
        raise HTTPException(status_code=404, detail="Agent session not found")
    presence.seven_day_pct = float(pct)
    presence.state = STATE_LIMIT_REACHED if pct >= 100 else STATE_ACTIVE
    presence.allowance_updated_at = utc_now()
    await db.flush()
    created = await request_handoffs_for_presence(db, presence, agent_hash)
    db.add(AuditLog(user_id=current_user.id, action=AUDIT_ACTION, resource_type="agent_presence",
                    resource_id=presence.id, project_id=presence.project_id,
                    details={"project_id": project_id, "agent_hash": agent_hash, "seven_day_pct": float(pct),
                             "automatic_requests": created}))
    await db.commit()
    return {"agent_hash": agent_hash, "seven_day_pct": float(pct), "state": presence.state,
            "automatic_requests": created}


__all__ = ["TEST_HOOKS_ENV", "router", "test_hooks_enabled"]
