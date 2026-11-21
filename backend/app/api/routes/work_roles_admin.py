"""Work roles admin API: functions with tool sets, roles, per-Workspace assignments and switch, SSO
mapping, tool catalog, audit log. Transport only; the rules live in ``services/work_role_model``.

All paths sit under ``/api/v1/work-roles``, apart from the platform RBAC roles ("Platform access").
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import require_visible_workspace
from ...services.auth import get_current_user
from ...services.work_role_model import admin_catalog, audit, sso_mapping, workspace_admin
from ...services.work_role_model.errors import WorkRoleError, may_admin_workspace, require_platform_admin
from ...services.work_role_model.tool_catalog import tool_catalog

router = APIRouter(prefix="/api/v1/work-roles", tags=["work-roles"])


async def _run(db: AsyncSession, call: Any) -> Any:
    try:
        result = await call
    except WorkRoleError as error:
        await db.rollback()
        raise error.http() from None
    await db.commit()
    return result


async def _read(call: Any) -> Any:
    try:
        return await call
    except WorkRoleError as error:
        raise error.http() from None


# --- functions --------------------------------------------------------------------------------------------------------

@router.get("/functions")
async def functions(workspace_id: str | None = None, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return {"functions": await _read(admin_catalog.list_functions(db, user, workspace_id))}


@router.post("/functions", status_code=201)
async def create_function(body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> dict:
    return await _run(db, admin_catalog.create_function(db, user, body))


@router.patch("/functions/{function_id}")
async def update_function(function_id: str, body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> dict:
    return await _run(db, admin_catalog.update_function(db, user, function_id, body))


@router.put("/functions/{function_id}/tools")
async def set_function_tools(function_id: str, body: dict[str, Any] = Body(...),
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await _run(db, admin_catalog.set_function_tools(db, user, function_id, body))


@router.delete("/functions/{function_id}", status_code=204)
async def delete_function(function_id: str, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> Response:
    await _run(db, admin_catalog.delete_function(db, user, function_id))
    return Response(status_code=204)


# --- roles ------------------------------------------------------------------------------------------------------------

@router.get("/roles")
async def roles(workspace_id: str | None = None, user: User = Depends(get_current_user),
                db: AsyncSession = Depends(get_db)) -> dict:
    return {"roles": await _read(admin_catalog.list_roles(db, user, workspace_id))}


@router.get("/roles/{role_id}")
async def role(role_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await _read(admin_catalog.get_role(db, user, role_id))


@router.post("/roles", status_code=201)
async def create_role(body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await _run(db, admin_catalog.create_role(db, user, body))


@router.patch("/roles/{role_id}")
async def update_role(role_id: str, body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await _run(db, admin_catalog.update_role(db, user, role_id, body))


@router.put("/roles/{role_id}/trusted")
async def set_trusted(role_id: str, body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await _run(db, admin_catalog.set_trusted(db, user, role_id, body))


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(role_id: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> Response:
    await _run(db, admin_catalog.delete_role(db, user, role_id))
    return Response(status_code=204)


# --- a Workspace ------------------------------------------------------------------------------------------------------
# An unknown Workspace and one the caller is no member of answer the same 404 before the route's own permission rule.

@router.get("/workspaces/{workspace_id}")
async def workspace(workspace_id: str, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)) -> dict:
    await require_visible_workspace(db, user.id, workspace_id)
    return await _read(workspace_admin.workspace_page(db, user, workspace_id))


@router.put("/workspaces/{workspace_id}/settings")
async def workspace_settings(workspace_id: str, body: dict[str, Any] = Body(...),
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await require_visible_workspace(db, user.id, workspace_id)
    return await _run(db, workspace_admin.set_switch(db, user, workspace_id, body))


@router.post("/workspaces/{workspace_id}/assignments", status_code=201)
async def create_assignment(workspace_id: str, body: dict[str, Any] = Body(...),
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await require_visible_workspace(db, user.id, workspace_id)
    return await _run(db, workspace_admin.create_assignment(db, user, workspace_id, body))


@router.patch("/workspaces/{workspace_id}/assignments/{assignment_id}")
async def update_assignment(workspace_id: str, assignment_id: str, body: dict[str, Any] = Body(...),
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await require_visible_workspace(db, user.id, workspace_id)
    return await _run(db, workspace_admin.set_assignment_active(db, user, workspace_id, assignment_id, body))


@router.get("/workspaces/{workspace_id}/effective")
async def effective(workspace_id: str, user_id: str | None = None, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)) -> dict:
    await require_visible_workspace(db, user.id, workspace_id)
    return await _read(workspace_admin.effective_view(db, user, workspace_id, user_id or user.id))


@router.get("/workspaces/{workspace_id}/me")
async def me(workspace_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await require_visible_workspace(db, user.id, workspace_id)
    return await _read(workspace_admin.effective_view(db, user, workspace_id, None))


# --- SSO mapping, catalog, audit --------------------------------------------------------------------------------------

@router.get("/sso-mapping")
async def sso_mappings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"providers": await _read(sso_mapping.list_mappings(db, user))}


@router.put("/sso-mapping/{provider_id}")
async def set_sso_mapping(provider_id: str, body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> dict:
    return await _run(db, sso_mapping.set_mapping(db, user, provider_id, body))


@router.get("/sso-mapping/{provider_id}/my-claims")
async def my_claims(provider_id: str, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return await sso_mapping.my_claims(db, user, provider_id)


@router.get("/tool-catalog")
async def catalog(function_id: str | None = None, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)) -> dict:
    entries: list[str] = []
    if function_id:
        row = await _read(admin_catalog.visible_function(db, user, function_id))
        entries = list(row.tools_json or [])
    return tool_catalog(entries)


@router.get("/audit")
async def audit_log(workspace_id: str | None = None, role_id: str | None = None, function_id: str | None = None,
                    before: datetime | None = None, limit: int = Query(default=audit.DEFAULT_PAGE, ge=1, le=1000),
                    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    try:
        if workspace_id:
            if not await may_admin_workspace(db, user, workspace_id):
                raise WorkRoleError("forbidden", "Only a Workspace admin reads this Workspace's role log.", 403)
        else:
            await require_platform_admin(db, user, "the global role log")
    except WorkRoleError as error:
        raise error.http() from None
    events, next_before = await audit.list_events(db, workspace_id=workspace_id, target_id=role_id or function_id,
                                                  before=before, limit=limit)
    return {"events": events, "next_before": next_before}
