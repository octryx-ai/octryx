"""Setting up a Work intake. Transport only.

Under ``/api/v1/secure-work/workspaces/{project_id}/intake``:

- ``GET  fields?source_type=&connection_id=``: what the connection offers (``intake/discovery``);
- ``POST count``: the live match count of a selection (Jira; ``{count: null}`` when not known);
- ``POST sample``: one page of a draft mapped to Work items, nothing stored (sources that offer it: Custom REST;
  others 422 ``intake_sample_unsupported``);
- ``POST``: create from a draft (inactive); ``GET /{id}``: the draft; ``PUT /{id}``: save a draft;
- ``POST /{id}/preview``: a dry run; ``POST /{id}/enable``: after a preview of the current settings, enable,
  schedule and start the first run; ``POST /{id}/disable``;
- ``POST /{id}/sync``: sync an enabled intake now (``intake/sync_now``: audited, 409 ``intake_not_enabled``).

Reads: work operators of the Workspace; writes: its admins or owners (a platform admin: every Workspace).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.secure_work.intake import discovery
from ...services.secure_work.intake.registry import require_source
from ...services.secure_work.intake.setup import (
    draft_of,
    first_run,
    preview_intake,
    save_intake,
    set_intake_active,
)
from ...services.secure_work.intake.sync_now import sync_now
from ...services.secure_work.servicenow.source import IntakeSourceError, source_error
from ._secure_work_scope import require_secure_work_scope
from .secure_work_intake import authorize_workspace, workspace_intake

router = APIRouter(
    prefix="/api/v1/secure-work/workspaces/{project_id}/intake", tags=["secure-work"],
    dependencies=[Depends(require_secure_work_scope)],
)


@router.get("/fields")
async def get_intake_fields(
    project_id: str, source_type: str, connection_id: str,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    return await discovery.discover(db, project_id, source_type, connection_id)


@router.post("/count")
async def post_intake_count(
    project_id: str, payload: dict[str, Any],
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    what = payload.get("what") if isinstance(payload.get("what"), dict) else {}
    return await discovery.count(db, project_id, str(payload.get("source_type") or ""),
                                 str(payload.get("connection_id") or ""), what)


@router.post("/sample")
async def post_intake_sample(
    project_id: str, payload: dict[str, Any],
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    source = require_source(payload.get("source_type"))
    if not hasattr(source, "sample"):
        raise HTTPException(status_code=422, detail={"state": "invalid_request", "code": "intake_sample_unsupported",
                                                     "message": "This source has no sample; run a preview."})
    result = await source.sample(db, user=current_user, project_id=project_id, draft=payload)
    await db.commit()  # the sample's REST calls are audited like every call
    return result


@router.post("")
async def post_intake(
    project_id: str, payload: dict[str, Any],
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    row = await save_intake(db, user=current_user, project_id=project_id, draft=payload)
    await db.commit()
    return draft_of(row)


@router.get("/{intake_id}")
async def get_intake_draft(
    project_id: str, intake_id: str,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id)
    return draft_of(await workspace_intake(db, project_id, intake_id))


@router.put("/{intake_id}")
async def put_intake_draft(
    project_id: str, intake_id: str, payload: dict[str, Any],
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    row = await workspace_intake(db, project_id, intake_id)
    await save_intake(db, user=current_user, project_id=project_id, draft=payload, row=row)
    await db.commit()
    return draft_of(row)


@router.post("/{intake_id}/preview")
async def post_intake_preview(
    project_id: str, intake_id: str,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    row = await workspace_intake(db, project_id, intake_id)
    try:
        result = await preview_intake(db, user=current_user, row=row)
    except IntakeSourceError as error:
        await db.rollback()
        raise source_error(error) from None
    await db.commit()
    return result


@router.post("/{intake_id}/enable")
async def post_intake_enable(
    project_id: str, intake_id: str,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    row = await workspace_intake(db, project_id, intake_id)
    await set_intake_active(db, user=current_user, row=row, active=True)
    await db.commit()
    try:  # the intake stays enabled whatever its first run answers; the run is in its history
        result: dict[str, Any] = {"first_run": await first_run(db, user=current_user, row=row)}
        await db.commit()
    except (HTTPException, IntakeSourceError) as error:
        await db.rollback()
        detail = error.detail if isinstance(error, HTTPException) else {"code": error.code}
        result = {"first_run": None, "first_run_error": detail}
    row = await workspace_intake(db, project_id, intake_id)
    return {**result, "intake": draft_of(row)}


@router.post("/{intake_id}/disable")
async def post_intake_disable(
    project_id: str, intake_id: str,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    row = await workspace_intake(db, project_id, intake_id)
    await set_intake_active(db, user=current_user, row=row, active=False)
    await db.commit()
    return draft_of(row)


@router.post("/{intake_id}/sync")
async def post_intake_sync(
    project_id: str, intake_id: str,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id, admin=True)
    row = await workspace_intake(db, project_id, intake_id)
    try:
        result = await sync_now(db, user=current_user, row=row)
    except IntakeSourceError as error:
        await db.rollback()
        raise source_error(error) from None
    await db.commit()
    return result
