"""Workspace scope of every Secure Work route, as one router dependency.

``require_work_operator`` gates the platform role; this dependency binds every route that addresses
Workspace data to the caller's Workspaces (``access.work_scope_project_ids``; a platform admin is
cross-workspace). It resolves what the request names before any handler runs, and a record of a Workspace outside
the caller's scope answers exactly like a missing one (the same 404 with the record's own wording):

- ``work_item_id`` (path, body or query): the item's Workspace (an item without one is admin-only, 403);
- ``change_unit_id`` (body or query): its item's Workspace (``Change Unit not found``, on an item-bound route
  ``Change Unit not found for this Work Item``);
- ``run_id`` of ``/coding-pipeline-runs/…``: its item's;
- for everyone but a platform admin these are answered here, before any role check of the handler, for a missing
  record too, so a missing and an unseen record cannot be told apart by what a handler would refuse next;
- a ``project_id`` query parameter or body field: must be one of the caller's Workspaces (for a platform admin a
  ``project_id`` that names no Workspace is 404 ``project_not_found``; for everyone else an unknown and a foreign
  Workspace are the same 403);
- the Workspace-bound config families (coding pipelines, repository profiles): the row's ``project_id``; a row
  without one is admin-only; creating such a row without a ``project_id`` is admin-only.

Related rows a handler consumes (configs, repository profiles, workflows, Change Plans, CI/CD providers and traces,
named in a request or stored on another row) are authorized where the service reads them, through the one scoped
loader ``services/secure_work/related_rows.py``.

Lists filter by the same scope in their services; workflows are scoped by ``workflow_access.py``.
"""

from __future__ import annotations

import json

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import (
    User,
    WorkCodingPipelineConfig,
    WorkCodingPipelineRun,
    WorkItem,
    WorkItemChangeUnit,
    WorkRepositoryProfile,
)
from ...services.access_control import require_existing_workspace
from ...services.auth import get_current_user
from ...services.secure_work.access import get_scoped_work_item, work_item_in_scope, work_scope_project_ids

_OUT_OF_SCOPE = "The requested Workspace data is outside your access"
_PREFIX = "/api/v1/secure-work"
# The Workspace-bound config families, by collection path: model, id parameter and the service's answer for an id
# that names nothing (a row of a Workspace outside the caller's scope answers the same).
CONFIG_FAMILIES = {
    "/coding-pipelines": (WorkCodingPipelineConfig, "config_id", "Coding pipeline config not found"),
    "/repository-profiles": (WorkRepositoryProfile, "profile_id", "Repository profile not found"),
}


def _family(path: str) -> tuple[str, type, str, str] | None:
    relative = path.removeprefix(_PREFIX)
    for collection, (model, param, missing) in CONFIG_FAMILIES.items():
        if relative == collection or relative.startswith(f"{collection}/"):
            return collection, model, param, missing
    return None


def _require(project_id: object, scope: set[str]) -> None:
    if not isinstance(project_id, str) or not project_id.strip() or project_id.strip() not in scope:
        raise HTTPException(status_code=403, detail=_OUT_OF_SCOPE)


async def _json_body(request: Request) -> dict:
    if request.method not in ("POST", "PUT", "PATCH"):
        return {}
    raw = await request.body()  # cached by Starlette; the handler reads the same body
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


UNIT_MISSING = "Change Unit not found"
_RUN_MISSING = "Coding pipeline run not found"
UNIT_MISSING_FOR_ITEM = "Change Unit not found for this Work Item"


def _body_id(request: Request, body: dict, key: str) -> str | None:
    """The trimmed body (else query) id under ``key``; blank is none, a non-string is 422."""
    value = body.get(key)
    if value is None:
        value = request.query_params.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{key} must be an id")
    return value.strip() or None


async def _require_change_unit(db: AsyncSession, request: Request, change_unit_id: str, scope: set[str]) -> None:
    unit = await db.get(WorkItemChangeUnit, change_unit_id)
    item = await db.get(WorkItem, unit.work_item_id) if unit is not None else None
    if item is None or not work_item_in_scope(scope, item):
        detail = UNIT_MISSING_FOR_ITEM if "work_item_id" in request.path_params else UNIT_MISSING
        raise HTTPException(status_code=404, detail=detail)


async def require_secure_work_scope(
    request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    scope = await work_scope_project_ids(db, current_user)
    body = await _json_body(request)
    await _require_addressed(db, request, body, current_user, scope)


async def _require_addressed(db: AsyncSession, request: Request, body: dict, current_user: User,
                             scope: set[str] | None) -> None:
    """The records the request addresses lie in the caller's scope (see the module doc)."""
    work_item_id, change_unit_id = _body_id(request, body, "work_item_id"), _body_id(request, body, "change_unit_id")
    project_id = request.query_params.get("project_id")
    if scope is None:
        # A platform admin sees every Workspace; a named one that does not exist is still the 404 of an unknown id.
        for named in (project_id, body.get("project_id")):
            if isinstance(named, str):
                await require_existing_workspace(db, named.strip() or None)
        return
    params, path = request.path_params, request.url.path
    if project_id and project_id.strip() and project_id.strip() not in scope:
        raise HTTPException(status_code=403, detail=_OUT_OF_SCOPE)
    if "work_item_id" in params:
        await get_scoped_work_item(db, current_user, params["work_item_id"])
    if body.get("project_id") not in (None, ""):
        _require(body.get("project_id"), scope)
    for item_id in {work_item_id, (request.query_params.get("work_item_id") or "").strip()} - {None, ""}:
        await get_scoped_work_item(db, current_user, item_id)
    if change_unit_id:
        await _require_change_unit(db, request, change_unit_id, scope)
    family = _family(path)
    if family is not None:
        collection, model, param, missing = family
        if param in params:
            row = await db.get(model, params[param])
            if row is None or (row.project_id is not None and row.project_id not in scope):
                raise HTTPException(status_code=404, detail=missing)  # missing and another Workspace's row alike
            _require(row.project_id, scope)  # a row without a Workspace is admin-only
            if request.method == "PUT" and "project_id" in body:
                _require(body.get("project_id"), scope)  # clearing or moving it: into the caller's Workspaces only
        elif request.method == "POST" and path.removeprefix(_PREFIX) == collection:
            _require(body.get("project_id"), scope)  # creating a Workspace-less row is admin-only
    if "run_id" in params and "/coding-pipeline-runs/" in path:
        run = await db.get(WorkCodingPipelineRun, params["run_id"])
        if run is None:  # answered here like another Workspace's run, before any role check of the handler
            raise HTTPException(status_code=404, detail=_RUN_MISSING)
        await get_scoped_work_item(db, current_user, run.work_item_id, missing=_RUN_MISSING)


__all__ = ["require_secure_work_scope"]
