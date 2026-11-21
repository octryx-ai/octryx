"""``GET /api/v1/workspaces/{id}/members``: who belongs to a Workspace (direct and via groups), for its members.

The companion's "Hand over…" picker lists these people; only active users, only ``{id, display_name}``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import ProjectGroup, User, UserGroup, UserProject
from ...services.auth import get_current_user
from ...services.secure_work.access import work_scope_project_ids

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/members", tags=["workspace-members"])


@router.get("")
async def list_members(workspace_id: str, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    scope = await work_scope_project_ids(db, current_user)
    if scope is not None and workspace_id not in scope:
        raise HTTPException(status_code=404, detail={"code": "unknown_workspace", "message": "Unknown Workspace."})
    direct = select(UserProject.user_id).where(UserProject.project_id == workspace_id)
    grouped = (select(UserGroup.user_id).join(ProjectGroup, ProjectGroup.group_id == UserGroup.group_id)
               .where(ProjectGroup.project_id == workspace_id))
    users = (await db.execute(select(User).where(User.id.in_(direct.union(grouped)), User.is_active.is_(True))
                              .order_by(User.username))).scalars().all()
    return {"members": [{"id": user.id, "display_name": user.display_name or user.username} for user in users]}
