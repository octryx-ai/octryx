"""Switching a workflow on or off. Only a platform admin; switching off stops new starts only."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog, FlowDefinition, User
from ..time_utils import utc_now

AUDIT_ACTION = "workflow.active_changed"


async def set_flow_active(db: AsyncSession, *, flow_id: str, active: bool, current_user: User) -> dict[str, Any]:
    # Flushed, not committed; the caller checked the admin right.
    flow = await db.get(FlowDefinition, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow definition not found")
    if flow.status == "archived":
        raise HTTPException(status_code=409, detail={
            "reason": "flow_archived", "message": "An archived workflow cannot be switched on or off."})
    before = bool(flow.is_active)
    if before != active:
        flow.is_active, flow.updated_at = active, utc_now()
        db.add(AuditLog(user_id=current_user.id, action=AUDIT_ACTION, resource_type="flow_definition",
                        project_id=flow.project_id,
                        resource_id=flow.id, details={"key": flow.key, "before": before, "after": active}))
        await db.flush()
    return {"id": flow.id, "key": flow.key, "is_active": bool(flow.is_active)}


__all__ = ["AUDIT_ACTION", "set_flow_active"]
