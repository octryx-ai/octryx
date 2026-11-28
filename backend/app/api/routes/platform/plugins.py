"""Plugins of the Octryx image, switched on per Workspace by its admin. Installing one means building it into the image;
the UI only switches it on or off."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....models.runtime.plugin_install import SCOPE_PLATFORM, STATUS_ACTIVE, STATUS_DISABLED, PluginInstall
from ....schemas.core.workspace_ref import WorkspaceId
from ....services.access_control import _user_is_admin, get_project_role_for_user, require_project_access
from ....services.auth import get_current_user
from ....services.data_access import bind_request_viewer
from ....services.plugins import image
from ....services.plugins import install as service
from ....services.plugins import ui as plugin_ui
from ....services.plugins.package import PackageError
from ....services.skill_catalog.errors import SkillCatalogError
from ....services.work_role_model.errors import WorkRoleError

router = APIRouter(prefix="/api/v1/plugins", tags=["plugins"])


class Activate(BaseModel):
    workspace_id: WorkspaceId = Field(min_length=1, max_length=36)


async def _may_install(db: AsyncSession, user: User, scope: str, workspace_id: str | None) -> None:
    if await _user_is_admin(db, user.id):
        return
    if scope == SCOPE_PLATFORM:
        raise HTTPException(403, detail={"code": "plugin_platform_admin_only",
                                         "message": "Only a platform admin installs a plugin for the platform."})
    role = await get_project_role_for_user(db, user.id, workspace_id) if workspace_id else None
    if role is None:
        raise HTTPException(404, detail={"code": "workspace_not_found", "message": "Workspace not found."})
    if role not in {"admin", "owner"}:
        raise HTTPException(403, detail={"code": "plugin_workspace_admin_only",
                                         "message": "A Workspace admin or owner installs plugins here."})


def _refused(error: Exception) -> HTTPException:
    if isinstance(error, PackageError):
        return HTTPException(422, detail={"code": "plugin_package_invalid", "issues": error.issues})
    if isinstance(error, service.PluginError):
        return service.to_http(error)
    if isinstance(error, SkillCatalogError):
        return HTTPException(error.status, detail=error.as_detail())
    if isinstance(error, WorkRoleError):
        return error.http()
    raise error


async def _visible(db: AsyncSession, user: User, row: PluginInstall) -> None:
    if row.scope == SCOPE_PLATFORM or await _user_is_admin(db, user.id):
        return
    if await get_project_role_for_user(db, user.id, row.workspace_id) is None:
        raise HTTPException(404, detail={"code": "plugin_not_found", "message": "Plugin install not found."})


@router.get("")
async def list_installs(workspace_id: str | None = None, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    query = select(PluginInstall).order_by(PluginInstall.name)
    if workspace_id:
        if not await _user_is_admin(db, user.id) and await get_project_role_for_user(db, user.id, workspace_id) is None:
            raise HTTPException(404, detail={"code": "workspace_not_found", "message": "Workspace not found."})
        query = query.where(or_(PluginInstall.workspace_id == workspace_id, PluginInstall.scope == SCOPE_PLATFORM))
    elif not await _user_is_admin(db, user.id):
        raise HTTPException(403, detail={"code": "plugin_list_needs_workspace",
                                         "message": "Name the Workspace (workspace_id)."})
    rows = [row for row in (await db.execute(query)).scalars().all()
            if not (workspace_id and image.is_image_part(row))]  # a Workspace sees its activation, not the image's part
    platform_admin = await _user_is_admin(db, user.id)
    role = await get_project_role_for_user(db, user.id, workspace_id) if workspace_id else None
    viewer = {"is_platform_admin": platform_admin,
              "can_install": platform_admin or role in {"admin", "owner"},
              "can_install_platform": platform_admin}
    return {"plugins": await service.install_views(db, rows), "viewer": viewer}


@router.get("/available")
async def list_available(workspace_id: str | None = None, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The plugins of the Octryx image and, with ``workspace_id``, whether each is on there. Members see the list,
    admins switch."""
    platform_admin = await _user_is_admin(db, user.id)
    role = await get_project_role_for_user(db, user.id, workspace_id) if workspace_id else None
    if workspace_id and role is None and not platform_admin:
        raise HTTPException(404, detail={"code": "workspace_not_found", "message": "Workspace not found."})
    if not workspace_id and not platform_admin:
        raise HTTPException(403, detail={"code": "plugin_list_needs_workspace",
                                         "message": "Name the Workspace (workspace_id)."})
    return {"plugins": await image.available(db, workspace_id),
            "viewer": {"is_platform_admin": platform_admin,
                       "can_activate": bool(workspace_id) and (platform_admin or role in {"admin", "owner"})}}


async def _switch(db: AsyncSession, user: User, plugin_key: str, workspace_id: str, on: bool) -> dict[str, Any]:
    await _may_install(db, user, "workspace", workspace_id)
    try:
        if on:
            row = await image.activate(db, plugin_key, workspace_id, user)
        else:
            row = await service.installed_here(db, plugin_key, "workspace", workspace_id)
            if row is None:
                raise service.PluginError("plugin_not_active", "This plugin is not on in this Workspace.", 404)
            await service.set_status(db, row, status=STATUS_DISABLED, user=user, reason="deactivated")
    except (service.PluginError, SkillCatalogError, WorkRoleError) as error:
        await db.rollback()
        raise _refused(error) from None
    except HTTPException:
        await db.rollback()
        raise
    await db.commit()
    return (await service.install_views(db, [row]))[0]


@router.post("/available/{plugin_key}/activate")
async def activate(plugin_key: str, body: Activate, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await require_project_access(db, user.id, body.workspace_id)
    return await _switch(db, user, plugin_key, body.workspace_id, True)


@router.post("/available/{plugin_key}/deactivate")
async def deactivate(plugin_key: str, body: Activate, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await require_project_access(db, user.id, body.workspace_id)
    return await _switch(db, user, plugin_key, body.workspace_id, False)


@router.get("/image")
async def image_plugins(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """What the last start did with the image's plugin folder (platform admins): per entry available (new),
    upgraded, unchanged, enabled, disabled (missing from the image) or failed with its reason."""
    if not await _user_is_admin(db, user.id):
        raise HTTPException(403, detail={"code": "plugin_platform_admin_only",
                                         "message": "Only a platform admin sees the image's plugin folder."})
    report = image.LAST_REPORT
    return report.as_dict() if report is not None else {"folder": str(image.plugin_dir()), "started_at": None,
                                                        "entries": []}


async def _row(db: AsyncSession, install_id: str) -> PluginInstall:
    row = await db.get(PluginInstall, install_id)
    if row is None:
        raise HTTPException(404, detail={"code": "plugin_not_found", "message": "Plugin install not found."})
    return row


@router.get("/{install_id}")
async def get_install(install_id: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _row(db, install_id)
    await _visible(db, user, row)
    return (await service.install_views(db, [row]))[0]


async def _set(db: AsyncSession, user: User, install_id: str, status: str) -> dict[str, Any]:
    row = await _row(db, install_id)
    await _visible(db, user, row)
    await _may_install(db, user, row.scope, row.workspace_id)
    await service.set_status(db, row, status=status, user=user)
    await db.commit()
    return (await service.install_views(db, [row]))[0]


@router.post("/{install_id}/disable")
async def disable(install_id: str, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await _set(db, user, install_id, STATUS_DISABLED)


@router.post("/{install_id}/enable")
async def enable(install_id: str, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await _set(db, user, install_id, STATUS_ACTIVE)


ui_router = APIRouter(tags=["plugins"])


class _MaskPluginUiToken(logging.Filter):
    # Access logs never keep a plugin UI token.
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "/plugin-ui/" in args[2]:
            record.args = (*args[:2], plugin_ui.masked_path(args[2]), *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_MaskPluginUiToken())


def _ui_refused(error: plugin_ui.PluginUiError) -> HTTPException:
    return HTTPException(error.status, detail={"code": error.code, "message": error.message})


class SettingsBody(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class BridgeBody(BaseModel):
    method: str = Field(min_length=1, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


async def _viewer_workspace(db: AsyncSession, user: User, row: PluginInstall, requested: str | None) -> str:
    # The install's Workspace, or for a platform install the viewer's current one.
    workspace_id = row.workspace_id or requested
    if not workspace_id:
        raise HTTPException(422, detail={"code": "plugin_workspace_required",
                                         "message": "Name the Workspace (context.workspace_id)."})
    if await get_project_role_for_user(db, user.id, workspace_id) is None:
        raise HTTPException(404, detail={"code": "workspace_not_found", "message": "Workspace not found."})
    return workspace_id


@router.get("/{install_id}/ui")
async def get_ui(install_id: str, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _row(db, install_id)
    await _visible(db, user, row)
    try:
        return plugin_ui.ui_view(row, user.id)
    except plugin_ui.PluginUiError as error:
        raise _ui_refused(error) from None


@router.get("/{install_id}/settings")
async def read_plugin_settings(install_id: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _row(db, install_id)
    await _visible(db, user, row)
    return await plugin_ui.read_settings(db, row)


@router.put("/{install_id}/settings")
async def save_plugin_settings(install_id: str, body: SettingsBody, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _row(db, install_id)
    await _visible(db, user, row)
    await _may_install(db, user, row.scope, row.workspace_id)
    try:
        saved = await plugin_ui.save_settings(db, row, body.values, user_id=user.id)
    except plugin_ui.PluginUiError as error:
        await db.rollback()
        raise _ui_refused(error) from None
    await db.commit()
    return saved


@router.post("/{install_id}/bridge")
async def call_bridge(install_id: str, body: BridgeBody, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _row(db, install_id)
    await _visible(db, user, row)
    workspace_id = await _viewer_workspace(db, user, row, str(body.context.get("workspace_id") or "") or None)
    try:
        outcome = await plugin_ui.bridge(db, row, user_id=user.id, workspace_id=workspace_id, method=body.method,
                                         params=body.params)
    except plugin_ui.PluginUiError as error:
        raise _ui_refused(error) from None
    await db.commit()
    return outcome


@ui_router.get("/plugin-ui/{install_id}/{token}/{path:path}", include_in_schema=False)
async def plugin_ui_file(install_id: str, token: str, path: str, db: AsyncSession = Depends(get_db)) -> Response:
    """A file of the plugin's UI; the token in the path is the only credential (GET on this install only)."""
    try:
        user_id = plugin_ui.read_token(token, install_id)
        bind_request_viewer(user_id)
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            raise plugin_ui.PluginUiError("plugin_not_found", "Not found.", 404)
        await _visible(db, user, await _row(db, install_id))
        found = await plugin_ui.ui_file(db, install_id, path)
    except plugin_ui.PluginUiError as error:
        if error.status == 401:
            raise _ui_refused(error) from None
        return Response(status_code=404, headers=plugin_ui.FILE_HEADERS)
    except HTTPException:
        return Response(status_code=404, headers=plugin_ui.FILE_HEADERS)
    return Response(content=found.content, media_type=found.content_type, headers=plugin_ui.FILE_HEADERS)
