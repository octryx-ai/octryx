"""ServiceNow intake per Workspace and the prepared work-note action."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import require_existing_workspace, require_project_access
from ....services.auth import get_current_user
from ....services.secure_work.access import get_scoped_work_item, require_work_operator, work_scope_project_ids
from ....services.secure_work.servicenow.config import normalize_intake
from ....services.secure_work.servicenow.intake import describe_intake, get_intake, limit_scope, list_runs, run_intake
from ....services.secure_work.servicenow.known_values import known_values
from ....services.secure_work.servicenow.source import IntakeSourceError, connector_config, source_error
from ....services.secure_work.servicenow.worknote import send_worknote
from ._secure_work_scope import require_secure_work_scope

router = APIRouter(
    prefix="/api/v1/secure-work", tags=["secure-work"], dependencies=[Depends(require_secure_work_scope)]
)


class WorknoteRequest(BaseModel):
    note_at: str | None = None
    confirm: bool = False


async def _authorize(db: AsyncSession, user: User, project_id: str, *, admin: bool) -> None:
    if await work_scope_project_ids(db, user) is None:
        await require_existing_workspace(db, user.id, project_id)
        return
    await require_project_access(db, user.id, project_id, require_admin=admin)


async def _intake(db: AsyncSession, project_id: str):
    row = await get_intake(db, project_id)
    if row is None:
        raise HTTPException(status_code=409, detail={"state": "needs_configuration",
                                                     "code": "servicenow_intake_not_configured"})
    return row


@router.get("/servicenow-intake/{project_id}")
async def get_servicenow_intake(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _authorize(db, current_user, project_id, admin=False)
    row = await get_intake(db, project_id)
    if row is None:
        intake = normalize_intake({})
        return {"project_id": project_id, "configured": False, "intake": intake,
                **await limit_scope(db, project_id, intake)}
    described = describe_intake(row)
    return {"project_id": project_id, "configured": True, **described,
            **await limit_scope(db, project_id, described["intake"], row)}


async def _run(project_id: str, current_user: User, db: AsyncSession, *, dry_run: bool) -> dict[str, Any]:
    await _authorize(db, current_user, project_id, admin=True)
    row = await _intake(db, project_id)
    try:
        result = await run_intake(db, row=row, user=current_user, dry_run=dry_run)
    except IntakeSourceError as error:
        await db.rollback()
        raise source_error(error) from None
    await db.commit()
    return result


@router.get("/servicenow-intake/{project_id}/limit-values")
async def servicenow_limit_values(
    project_id: str, table: str = "incident", current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize(db, current_user, project_id, admin=True)
    try:
        return await known_values(await connector_config(db, project_id), limited=True, table=table)
    except IntakeSourceError as error:
        raise source_error(error) from None


@router.post("/servicenow-intake/{project_id}/preview")
async def preview_servicenow_intake(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _run(project_id, current_user, db, dry_run=True)


@router.post("/servicenow-intake/{project_id}/sync")
async def sync_servicenow_intake(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _run(project_id, current_user, db, dry_run=False)


@router.get("/servicenow-intake/{project_id}/runs")
async def servicenow_intake_runs(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _authorize(db, current_user, project_id, admin=False)
    row = await get_intake(db, project_id)
    return {"project_id": project_id, "runs": await list_runs(db, row) if row is not None else []}


@router.post("/work-items/{work_item_id}/servicenow-worknote")
async def servicenow_worknote(
    work_item_id: str, body: WorknoteRequest, current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_work_operator(db, current_user)
    item = await get_scoped_work_item(db, current_user, work_item_id)
    result = await send_worknote(db, item=item, user=current_user, note_at=body.note_at, confirm=body.confirm)
    await db.commit()
    return result
