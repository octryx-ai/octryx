"""MCP servers allowed per Workspace."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import _user_is_admin, require_existing_workspace
from ....services.auth import get_current_user
from ....services.mcp_workspace_allow import (
    McpAllowError,
    allow_status,
    is_own_registration,
    server_allow,
    set_server_allow,
    set_workspace_server,
    workspace_servers,
)
from ....services.workspace_settings.bounds import LooseningRefusedError, check_mcp_allow

router = APIRouter(prefix="/api/v1/admin", tags=["mcp-workspace-allow"])


def _client_manager() -> Any:
    from ....plugins.mcp.client import mcp_client_manager

    return mcp_client_manager


async def _admin(db: AsyncSession, user: User) -> None:
    if not await _user_is_admin(db, user.id):
        raise HTTPException(status_code=403, detail="Platform admin role required")


async def _workspace_admin(db: AsyncSession, user: User, workspace_id: str) -> bool:
    if await _user_is_admin(db, user.id):
        await require_existing_workspace(db, user.id, workspace_id)
        return True
    from .workspace_models import require_workspace_admin

    await require_workspace_admin(db, user, workspace_id)
    return False


def _refused(error: McpAllowError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code})


@router.get("/mcp-servers/allow")
async def get_allow_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await _admin(db, user)
    return {"servers": await allow_status(db, viewer_id=user.id, mcp_client_manager=_client_manager())}


@router.get("/mcp-servers/{server_id}/allow")
async def get_server_allow(
    server_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await _admin(db, user)
    try:
        return await server_allow(db, server_id=server_id, viewer_id=user.id, mcp_client_manager=_client_manager())
    except McpAllowError as error:
        raise _refused(error) from None


@router.put("/mcp-servers/{server_id}/allow")
async def put_server_allow(
    server_id: str,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _admin(db, user)
    workspace_ids = body.get("workspace_ids")
    for workspace_id in workspace_ids if isinstance(workspace_ids, list) else []:
        await require_existing_workspace(db, user.id, str(workspace_id))
    try:
        await set_server_allow(db, server_id=server_id, workspace_ids=body.get("workspace_ids"),
                               tools=body.get("tools"), actor_id=user.id)
    except McpAllowError as error:
        await db.rollback()
        raise _refused(error) from None
    await db.commit()
    return await server_allow(db, server_id=server_id, viewer_id=user.id, mcp_client_manager=_client_manager())


@router.get("/workspaces/{workspace_id}/mcp-servers")
async def get_workspace_servers(
    workspace_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await _workspace_admin(db, user, workspace_id)
    try:
        return {"servers": await workspace_servers(db, workspace_id=workspace_id)}
    except McpAllowError as error:
        raise _refused(error) from None


@router.put("/workspaces/{workspace_id}/mcp-servers/{server_id}")
async def put_workspace_server(
    workspace_id: str,
    server_id: str,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    platform_admin = await _workspace_admin(db, user, workspace_id)
    try:
        if not platform_admin:
            check_mcp_allow(allowed=body.get("allowed") is True,
                            own_server=await is_own_registration(db, server_id=server_id, workspace_id=workspace_id))
        await set_workspace_server(db, workspace_id=workspace_id, server_id=server_id,
                                   allowed=body.get("allowed") is True, actor_id=user.id)
    except LooseningRefusedError as error:
        raise HTTPException(status_code=403, detail={"code": error.code, "path": error.path,
                                                     "reason": error.reason}) from None
    except McpAllowError as error:
        await db.rollback()
        raise _refused(error) from None
    await db.commit()
    return {"workspace_id": workspace_id, "server_id": server_id, "allowed": body.get("allowed") is True}


__all__ = ["router"]
