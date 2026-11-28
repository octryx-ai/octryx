"""Classification policy matrix and the Workspace policy view (read-only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Project, User
from ....services.access_control import _user_is_admin, get_project_role_for_user
from ....services.auth import get_current_user
from ....services.data_classification.policy_matrix import load_classification_policy
from ....services.data_classification.policy_matrix_admin import policy_view
from ....services.data_classification.workspace_policy_summary import workspace_policy_summary
from .classification_policy_versions import router as versions_router

router = APIRouter(tags=["data-classification"])
router.include_router(versions_router)

NOT_FOUND = "Workspace not found"
@router.get("/api/v1/admin/data-classification/policy")
async def get_classification_policy(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    can_edit = await _user_is_admin(db, current_user.id)
    return await policy_view(db, await load_classification_policy(db), can_edit=can_edit)


@router.get("/api/v1/workspaces/{project_id}/policy-summary")
async def get_workspace_policy_summary(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    role = await get_project_role_for_user(db, current_user.id, project_id)
    project = await db.get(Project, project_id) if role is not None else None
    if project is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return {**await workspace_policy_summary(db, project), "can_edit": await _user_is_admin(db, current_user.id)}


__all__ = ["router"]
