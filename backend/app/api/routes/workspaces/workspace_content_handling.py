"""A Workspace's sensitive-content handling (``content_security.handling``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import get_project_role_for_user, require_project_access
from ....services.auth import get_current_user
from ....services.content_security.handling_settings import handling_view, set_governance_alias, set_handling

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspace-content-handling"])
EDIT_ROLES = frozenset({"admin", "owner"})


@router.get("/{workspace_id}/content-handling")
async def get_content_handling(workspace_id: str, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    await require_project_access(db, user.id, workspace_id)
    role = await get_project_role_for_user(db, user.id, workspace_id)
    return await handling_view(db, workspace_id, can_edit=role in EDIT_ROLES)


@router.put("/{workspace_id}/content-handling/governance-alias")
async def put_governance_alias(workspace_id: str, body: Any = Body(...), user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    await require_project_access(db, user.id, workspace_id, require_admin=True)
    view = await set_governance_alias(db, workspace_id, body, user_id=user.id)
    await db.commit()
    return view


@router.put("/{workspace_id}/content-handling/{kind}")
async def put_content_handling(workspace_id: str, kind: str, body: Any = Body(...),
                               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_project_access(db, user.id, workspace_id, require_admin=True)
    entry = await set_handling(db, workspace_id, kind, body, user_id=user.id)
    await db.commit()
    return entry


__all__ = ["router"]
