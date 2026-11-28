"""Allow an MCP server in Workspaces: the first writer of ``mcp_policy``. A registered server is deny-by-default in
every Workspace."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..models import McpServerRegistration, Project
from .admin.governance.admin_config_audit_service import record_admin_config_audit
from .mcp_access_policy import MCP_POLICY_CONFIG_KEY, mcp_server_access_decision, selected_mcp_tools
from .mcp_server_registry_config import registration_is_connected
from .project.private_workspace import foreign_private_filter

AUDIT_ACTION = "admin.mcp.workspace_allow_changed"
MAX_SELECTED_TOOLS = 200
ERROR_SERVER_UNKNOWN = "mcp_server_unknown"
ERROR_WORKSPACE_UNKNOWN = "mcp_workspace_unknown"
ERROR_WORKSPACE_FOREIGN = "mcp_server_owned_by_another_workspace"
ERROR_TOOLS_INVALID = "mcp_tools_invalid"


class McpAllowError(ValueError):
    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _names(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def apply_server_allow(config: Any, server: str, *, allowed: bool, tools: list[str] | None) -> dict[str, Any]:
    config = dict(config) if isinstance(config, dict) else {}
    stored = config.get(MCP_POLICY_CONFIG_KEY)
    policy = dict(stored) if isinstance(stored, dict) else {}
    lookup = server.strip().lower()
    enabled = [name for name in _names(policy.get("enabled_servers")) if name.lower() != lookup]
    selected = {
        name: list(items) for name, items in (policy.get("selected_tools") or {}).items()
        if str(name).strip().lower() != lookup
    } if isinstance(policy.get("selected_tools"), dict) else {}
    if allowed:
        enabled.append(server)
        if tools is not None:
            selected[server] = sorted(set(tools))
    policy["enabled_servers"] = sorted(enabled, key=str.lower)
    if selected:
        policy["selected_tools"] = selected
    else:
        policy.pop("selected_tools", None)
    config[MCP_POLICY_CONFIG_KEY] = policy
    return config


def _tools(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_SELECTED_TOOLS:
        raise McpAllowError(ERROR_TOOLS_INVALID)
    tools = [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]
    if len(tools) != len(value) or not tools:
        raise McpAllowError(ERROR_TOOLS_INVALID)
    return tools


async def _registration(db: AsyncSession, server_id: str) -> McpServerRegistration:
    registration = await db.get(McpServerRegistration, server_id)
    if registration is None:
        raise McpAllowError(ERROR_SERVER_UNKNOWN, status=404)
    return registration


async def _workspaces(db: AsyncSession, registration: McpServerRegistration, viewer_id: str) -> list[Project]:
    query = select(Project).where(Project.is_active.is_(True), foreign_private_filter(viewer_id)).order_by(Project.name)
    if registration.owner_scope == "workspace":
        query = query.where(Project.id == registration.workspace_id)
    return list((await db.execute(query)).scalars().all())


def _allow_row(registration: McpServerRegistration, project: Project) -> dict[str, Any]:
    allowed = mcp_server_access_decision(registration.name, project.config).allowed
    selected = selected_mcp_tools(registration.name, project.config)
    return {
        "workspace_id": project.id,
        "name": project.name,
        "allowed": allowed,
        "tools": sorted(selected) if (allowed and selected is not None) else None,
    }


async def server_allow(db: AsyncSession, *, server_id: str, viewer_id: str, mcp_client_manager: Any) -> dict[str, Any]:
    registration = await _registration(db, server_id)
    connected = await registration_is_connected(registration, mcp_client_manager=mcp_client_manager)
    tools = [tool.name for tool in mcp_client_manager.get_tools(registration.name)] if connected else []
    return {
        "server_id": registration.id,
        "name": registration.name,
        "connected": connected,
        "tools": tools,
        "workspaces": [_allow_row(registration, project) for project in await _workspaces(db, registration, viewer_id)],
    }


async def set_server_allow(
    db: AsyncSession, *, server_id: str, workspace_ids: Any, tools: Any, actor_id: str
) -> None:
    registration = await _registration(db, server_id)
    wanted = set(_names(workspace_ids))
    selected = _tools(tools)
    projects = await _workspaces(db, registration, actor_id)
    known = {project.id for project in projects}
    if wanted - known:
        foreign = registration.owner_scope == "workspace"
        raise McpAllowError(ERROR_WORKSPACE_FOREIGN if foreign else ERROR_WORKSPACE_UNKNOWN)
    for project in projects:
        await _write(db, registration, project, allowed=project.id in wanted, tools=selected, actor_id=actor_id)
    await db.flush()


async def set_workspace_server(
    db: AsyncSession, *, workspace_id: str, server_id: str, allowed: bool, actor_id: str
) -> None:
    registration = await _registration(db, server_id)
    project = await db.get(Project, workspace_id)
    if project is None:
        raise McpAllowError(ERROR_WORKSPACE_UNKNOWN, status=404)
    if registration.owner_scope == "workspace" and registration.workspace_id != project.id:
        raise McpAllowError(ERROR_WORKSPACE_FOREIGN)
    keep = selected_mcp_tools(registration.name, project.config)
    await _write(db, registration, project, allowed=allowed, tools=sorted(keep) if keep else None, actor_id=actor_id)
    await db.flush()


async def _write(
    db: AsyncSession, registration: McpServerRegistration, project: Project, *, allowed: bool,
    tools: list[str] | None, actor_id: str,
) -> None:
    before = _allow_row(registration, project)
    project.config = apply_server_allow(project.config, registration.name, allowed=allowed, tools=tools)
    flag_modified(project, "config")
    after = _allow_row(registration, project)
    if before == after:
        return
    record_admin_config_audit(
        db, actor_user_id=actor_id, action=AUDIT_ACTION, resource_type="workspace_mcp_policy",
        resource_id=project.id, project_id=project.id, before=before, after=after,
        details={"server_id": registration.id},
    )


async def is_own_registration(db: AsyncSession, *, server_id: str, workspace_id: str) -> bool:
    registration = await _registration(db, server_id)
    return registration.owner_scope == "workspace" and registration.workspace_id == workspace_id


async def workspace_servers(db: AsyncSession, *, workspace_id: str) -> list[dict[str, Any]]:
    # Another Workspace's registrations and inactive ones are never listed.
    project = await db.get(Project, workspace_id)
    if project is None:
        raise McpAllowError(ERROR_WORKSPACE_UNKNOWN, status=404)
    registrations = (
        await db.execute(
            select(McpServerRegistration)
            .where(McpServerRegistration.is_active.is_(True))
            .order_by(McpServerRegistration.name)
        )
    ).scalars().all()
    return [
        {
            "server_id": registration.id,
            "server_name": registration.name,
            "own": registration.owner_scope == "workspace",
            **_allow_row(registration, project),
        }
        for registration in registrations
        if registration.owner_scope != "workspace" or registration.workspace_id == project.id
    ]


async def allow_status(db: AsyncSession, *, viewer_id: str, mcp_client_manager: Any) -> list[dict[str, Any]]:
    registrations = (
        await db.execute(select(McpServerRegistration).order_by(McpServerRegistration.name))
    ).scalars().all()
    projects = list((await db.execute(
        select(Project).where(Project.is_active.is_(True), foreign_private_filter(viewer_id)))).scalars().all())
    rows = []
    for registration in registrations:
        scoped = [p for p in projects if registration.owner_scope != "workspace" or p.id == registration.workspace_id]
        allowed_in = [p for p in scoped if mcp_server_access_decision(registration.name, p.config).allowed]
        connected = await registration_is_connected(registration, mcp_client_manager=mcp_client_manager)
        rows.append({
            "server_id": registration.id,
            "name": registration.name,
            "registered": True,
            "connected": connected,
            "allowed_workspaces": len(allowed_in),
            "tools_visible": connected and bool(allowed_in),
            "tool_count": len(mcp_client_manager.get_tools(registration.name)) if connected else 0,
        })
    return rows


__all__ = [
    "McpAllowError",
    "allow_status",
    "is_own_registration",
    "apply_server_allow",
    "server_allow",
    "set_server_allow",
    "set_workspace_server",
    "workspace_servers",
]
