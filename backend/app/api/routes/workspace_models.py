"""Workspace → Models. Transport only; the contract and the
derivation live in ``services/workspace_models``.

- ``GET /api/v1/admin/workspaces/{id}/models`` — ``{contract, models, level, seat_checks}``; ``models`` by display
  name with clearance, approvals, temperature and where each can be used.
- ``PUT /api/v1/admin/workspaces/{id}/models`` — the contract ``{mode, selected, default, task_overrides, seat}``;
  422 ``{code, path, reason}`` for an unknown or not-cleared model, a default outside the list, an invalid seat.

Workspace admins and owners, and platform admins. A Workspace admin or owner may only narrow (no newly allowed
model, no switch to all cleared models, no seat or company models in ``/model`` that were off): 403
``{code: platform_admin_required, path, reason}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import get_project_role_for_user
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth import get_current_user
from ...services.workspace_models.contract import WorkspaceModelsError
from ...services.workspace_models.store import read_models, save_models
from ...services.workspace_settings.bounds import LooseningRefusedError

router = APIRouter(prefix="/api/v1/admin/workspaces", tags=["workspace-models"])


async def require_workspace_admin(db: AsyncSession, user: User, project_id: str) -> None:
    role = await get_project_role_for_user(db, user.id, project_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Workspace admin or owner role required")


@router.get("/{project_id}/models")
async def get_workspace_models(
    project_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await require_workspace_admin(db, user, project_id)
    return await read_models(db, project_id)


@router.put("/{project_id}/models")
async def put_workspace_models(
    project_id: str,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_workspace_admin(db, user, project_id)
    try:
        view = await save_models(
            db, project_id, body, actor_id=user.id, platform_admin=await is_global_admin(db, user.id)
        )
    except LooseningRefusedError as error:
        await db.rollback()
        raise HTTPException(
            status_code=403, detail={"code": error.code, "path": error.path, "reason": error.reason}
        ) from None
    except WorkspaceModelsError as error:
        await db.rollback()
        raise HTTPException(
            status_code=422, detail={"code": error.code, "path": error.path, "reason": error.reason}
        ) from None
    await db.commit()
    return view


__all__ = ["router"]
