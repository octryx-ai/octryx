"""Work intake per Workspace. Transport only.

- ``GET /workspaces/{project_id}/intake``: every source of the Workspace with Connection · In Knowledge · In
  Work, and its intakes (``services/secure_work/intake/overview``);
- ``GET /workspaces/{project_id}/intake/{intake_id}/runs``: the intake's last runs, newest first.

Work operators of the Workspace (a platform admin: every Workspace). Configs of other Workspaces never appear.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User, WorkItemSyncConfig
from ...services.access_control import require_project_access, require_visible_workspace
from ...services.auth import get_current_user
from ...services.secure_work.access import require_work_operator, work_scope_project_ids
from ...services.secure_work.intake.overview import intake_overview
from ...services.secure_work.intake.runs import MAX_RUNS, list_intake_runs
from ._secure_work_scope import require_secure_work_scope

router = APIRouter(
    prefix="/api/v1/secure-work", tags=["secure-work"], dependencies=[Depends(require_secure_work_scope)]
)


async def authorize_workspace(db: AsyncSession, user: User, project_id: str, *, admin: bool = False) -> None:
    """A work operator with access to the Workspace (``admin``: its admin or owner). An unknown Workspace and one the
    caller is no member of are the same 404 ``project_not_found`` (``require_visible_workspace``)."""
    await require_work_operator(db, user)
    await require_visible_workspace(db, user.id, project_id)
    if await work_scope_project_ids(db, user) is None:
        return  # a platform admin
    await require_project_access(db, user.id, project_id, require_admin=admin)


async def workspace_intake(db: AsyncSession, project_id: str, intake_id: str) -> WorkItemSyncConfig:
    row = await db.get(WorkItemSyncConfig, intake_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Intake not found")
    return row


@router.get("/workspaces/{project_id}/intake")
async def get_workspace_intake(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id)
    return await intake_overview(db, project_id)


@router.get("/workspaces/{project_id}/intake/{intake_id}/runs")
async def get_workspace_intake_runs(
    project_id: str,
    intake_id: str,
    limit: int = Query(MAX_RUNS, ge=1, le=MAX_RUNS),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id)
    row = await workspace_intake(db, project_id, intake_id)
    return {"intake_id": row.id, "runs": await list_intake_runs(db, row, limit)}
