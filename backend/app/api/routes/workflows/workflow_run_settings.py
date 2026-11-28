"""Where and what a workflow run can start, the Workspace's triage routing, and the loop and budget limits."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....models.runtime.secure_work import WorkItem
from ....services.admin.governance.admin_access_service import is_global_admin
from ....services.auth import get_current_user
from ....services.secure_work.access import work_item_in_scope, work_scope_project_ids
from ....services.workflow_runs.access import require_workspace_view
from ....services.workflow_runs.limits import MAX_LOOP_CEILING, loop_ceiling, patch_run_limits, set_loop_ceiling
from ....services.workflow_runs.records import WorkflowRunError
from ....services.workflow_runs.run_start import startable_workflows_for
from ._workflow_run_http import CeilingRequest, WorkItemLimitsRequest, _http

router = APIRouter()


@router.get("/runtime-targets")
async def runtime_targets(
    project_id: str | None = Query(default=None, max_length=36),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Where the caller can start a run: the Server, a terminal, their devices' allowed folders; the default is the
    target of their most recent run in this Workspace."""
    from ....services.workflow_runs.runtime_target.target import target_choices

    try:
        await require_workspace_view(db, current_user, project_id)
    except WorkflowRunError as error:
        raise _http(error) from error
    # ``auto`` (device-first with a seat) is the default; a requester who explicitly chose a target last keeps it.
    return await target_choices(db, user=current_user, project_id=project_id)


@router.get("/startable")
async def startable_workflows(
    project_id: str | None = Query(default=None, max_length=36),
    work_item_id: str | None = Query(default=None, max_length=36),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The published workflows a run can start, with ``work_item_id`` also the item's ``entry_workflow``. The person
    still chooses: nothing starts by itself."""
    from ....services.workflow_runs.triage_routing import entry_workflow_for, routes_for_workspace

    try:
        await require_workspace_view(db, current_user, project_id)
    except WorkflowRunError as error:
        raise _http(error) from error
    workflows = await startable_workflows_for(db, project_id=project_id)
    item = await db.get(WorkItem, work_item_id) if work_item_id else None
    entry = None
    if item is not None and work_item_in_scope(await work_scope_project_ids(db, current_user), item):
        key = entry_workflow_for(item, await routes_for_workspace(db, item.project_id or project_id))
        entry = key if any(workflow["key"] == key for workflow in workflows) else None
    return {"workflows": workflows, **({"entry_workflow": entry} if work_item_id else {})}


async def _routing_workspace(db: AsyncSession, user: User, project_id: str, *, write: bool):
    from ....models import Project
    from ....services.access_control import get_project_role_for_user, workspace_not_found

    role = await get_project_role_for_user(db, user.id, project_id)
    admin = await is_global_admin(db, user.id)
    project = await db.get(Project, project_id) if role is not None or admin else None
    if project is None:
        raise workspace_not_found()
    can_edit = admin or role in {"admin", "owner"}
    if write and not can_edit:
        raise HTTPException(status_code=403, detail={"code": "workspace_admin_only",
                                                     "message": "Workspace admin or owner role required."})
    return project, can_edit


@router.get("/triage-routing")
async def get_triage_routing(
    project_id: str = Query(min_length=1, max_length=36),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The Workspace's routing by type (spec B/C §1): ``{project_id, routes, defaults, effective, source, can_edit}``;
    a triage definition's outcome ``routing`` block still overrides it per run."""
    from ....services.workflow_runs.triage_routing import settings_payload

    project, can_edit = await _routing_workspace(db, current_user, project_id, write=False)
    return settings_payload(project, can_edit=can_edit)


@router.put("/triage-routing")
async def put_triage_routing(
    body: dict = Body(...),
    project_id: str = Query(min_length=1, max_length=36),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the Workspace's routes: ``{"routes": {type: workflow_key | null}}`` (``null`` switches a type off;
    an empty object goes back to the defaults). Workspace admin/owner; 422 with ``{code, field}`` otherwise."""
    from ....services.workflow_runs.triage_routing import RoutingSettingsError, set_workspace_routes, settings_payload

    project, can_edit = await _routing_workspace(db, current_user, project_id, write=True)
    try:
        await set_workspace_routes(db, project=project, value=body, actor_id=current_user.id)
    except RoutingSettingsError as error:
        raise HTTPException(status_code=422, detail={"errors": [{"code": error.code, "field": error.field}]}) from None
    await db.commit()
    await db.refresh(project)
    return settings_payload(project, can_edit=can_edit)


@router.get("/limits")
async def get_limits(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"loop_ceiling": await loop_ceiling(db), "max_loop_ceiling": MAX_LOOP_CEILING,
            "editable": await is_global_admin(db, current_user.id)}


@router.put("/limits")
async def put_limits(
    body: CeilingRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Only a platform admin changes the ceiling every run loop is capped by."""
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "platform_admin_only",
                                                     "message": "Only a platform admin changes the loop ceiling."})
    try:
        value = await set_loop_ceiling(db, body.loop_ceiling, user_id=current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "invalid_ceiling", "message": str(error)}) from error
    await db.commit()
    return {"loop_ceiling": value, "max_loop_ceiling": MAX_LOOP_CEILING, "editable": True}


async def _work_item_for_limits(db: AsyncSession, work_item_id: str, user: User, *, write: bool) -> WorkItem:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_work_item", "message": "Unknown Work item."})
    if not work_item_in_scope(await work_scope_project_ids(db, user), item):
        raise HTTPException(status_code=403 if write else 404,
                            detail={"code": "work_item_scope", "message": "Not a member of the item's Workspace."})
    return item


@router.get("/work-items/{work_item_id}/limits")
async def get_work_item_limits(
    work_item_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    item = await _work_item_for_limits(db, work_item_id, current_user, write=False)
    return {"run_limits": dict(item.run_limits or {}), "loop_ceiling": await loop_ceiling(db)}


@router.put("/work-items/{work_item_id}/limits")
async def put_work_item_limits(
    work_item_id: str, body: WorkItemLimitsRequest, current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The Work item's override of every loop's n and of the run budget, as a patch (left-out keys stay, ``null``
    removes one); runs started afterwards use it, and a Work item without its own budget key inherits its parent's."""
    item = await _work_item_for_limits(db, work_item_id, current_user, write=True)
    try:
        limits = patch_run_limits(item.run_limits, body.model_dump(include=body.model_fields_set))
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "invalid_run_limits", "message": str(error)}) from error
    item.run_limits = limits or None
    await db.commit()
    return {"run_limits": limits, "loop_ceiling": await loop_ceiling(db)}
