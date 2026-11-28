"""Tool and approval policies: which tool calls wait for a person (platform admins only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import McpServerRegistration, Project, User
from ....services.mcp_access_policy import mcp_server_access_decision
from ....services.tool_approval.policy import (
    APPROVAL_POLICY_CONFIG_KEY,
    MODE_ADD,
    MODE_INHERIT,
    RISKS,
    ToolApprovalPolicyError,
    effective_policy,
    platform_default,
    refresh_platform_default,
    save_platform_default,
    save_workspace_policy,
)
from ....tools.definitions import get_all_definitions, get_tool_definition_metadata
from ..policy.policy_engine import require_admin

router = APIRouter(prefix="/api/v1/admin/tool-approvals", tags=["tool-approvals"])


def _invalid(error: ToolApprovalPolicyError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "path": error.path})


def _workspace_row(project: Project) -> dict[str, Any]:
    config = project.config if isinstance(project.config, dict) else {}
    stored = config.get(APPROVAL_POLICY_CONFIG_KEY)
    mode = MODE_ADD if isinstance(stored, dict) and stored.get("mode", MODE_ADD) == MODE_ADD else MODE_INHERIT
    keys = ("require_for_risks", "require_for_tools", "exempt_tools")
    own = {key: list(stored.get(key) or []) if mode == MODE_ADD else [] for key in keys}
    return {"id": project.id, "name": project.name, "mode": mode, "own": own, "effective": effective_policy(config)}


async def _payload(db: AsyncSession) -> dict[str, Any]:
    await refresh_platform_default(db)
    stmt = select(Project).where(Project.is_active.is_(True)).order_by(Project.name)
    projects = (await db.execute(stmt)).scalars().all()
    servers = sorted({str(name) for name in (await db.execute(select(McpServerRegistration.name))).scalars()})
    tools = [{"name": name, "risk": get_tool_definition_metadata(name).risk} for name in sorted(get_all_definitions())]
    return {
        "default": platform_default(),
        "risks": list(RISKS),
        "tools": tools,
        "workspaces": [_workspace_row(project) for project in projects],
        "mcp": {
            "servers": servers,
            "workspaces": [
                {"id": project.id, "name": project.name,
                 "servers": {server: mcp_server_access_decision(server, project.config).allowed for server in servers}}
                for project in projects
            ],
        },
    }


@router.get("")
async def get_tool_approvals(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await _payload(db)


@router.put("/default")
async def put_default(body: dict[str, Any] = Body(...), user: User = Depends(require_admin),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await save_platform_default(db, body, actor_id=user.id)
    except ToolApprovalPolicyError as error:
        raise _invalid(error) from None
    await db.commit()
    return await _payload(db)


@router.put("/workspaces/{project_id}")
async def put_workspace(project_id: str, body: dict[str, Any] = Body(...), user: User = Depends(require_admin),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        await save_workspace_policy(db, project, body, actor_id=user.id)
    except ToolApprovalPolicyError as error:
        raise _invalid(error) from None
    await db.commit()
    return await _payload(db)


__all__ = ["router"]
