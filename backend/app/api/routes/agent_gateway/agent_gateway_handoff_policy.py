"""The Workspace handoff policy REST."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Project, User
from ....services.access_control import get_project_role_for_user
from ....services.agent_gateway.handoff_policy import set_workspace_handoff_policy
from ....services.agent_gateway.handoff_policy_keys import HandoffPolicyError, handoff_policy_from_config
from ....services.auth import get_current_user

router = APIRouter(tags=["agent-gateway"])
PATH = "/api/v1/workspaces/{project_id}/agent-gateway/handoff-policy"


async def _workspace(db: AsyncSession, user: User, project_id: str, *, write: bool) -> tuple[Project, bool]:
    role = await get_project_role_for_user(db, user.id, project_id)
    project = await db.get(Project, project_id) if role is not None else None
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    can_edit = role in {"admin", "owner"}
    if write and not can_edit:
        raise HTTPException(status_code=403, detail="Workspace admin or owner role required")
    return project, can_edit


def _payload(project: Project, can_edit: bool) -> dict[str, Any]:
    policy, source = handoff_policy_from_config(project.config)
    return {"project_id": project.id, "handoff": policy.as_dict(), "source": source, "can_edit": can_edit}


@router.get(PATH)
async def get_handoff_policy(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=False)
    return _payload(project, can_edit)


@router.put(PATH)
async def put_handoff_policy(
    project_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=True)
    try:
        await set_workspace_handoff_policy(db, project=project, value=body, actor_id=current_user.id)
    except HandoffPolicyError as error:
        raise HTTPException(status_code=422,
                            detail={"errors": [{"code": error.reason, "field": error.path}]}) from None
    await db.commit()
    await db.refresh(project)
    return _payload(project, can_edit)


__all__ = ["router"]
