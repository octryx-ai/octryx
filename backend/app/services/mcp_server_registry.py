"""Workspace-scoped MCP server registry and governed connection lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import McpServerRegistration, Project
from ..models.runtime.mcp_server import (
    MCP_OWNER_PLATFORM,
    MCP_OWNER_WORKSPACE,
)
from ..models.security.compliance_audit import (
    AUDIT_ADMIN_CHANGE,
    OUTCOME_ALLOWED,
)
from ..plugins.mcp.models import MCPServerConfig
from .compliance_audit.service import create_audit_record
from .mcp_access_policy import mcp_server_access_decision
from .mcp_audit_vocabulary import READINESS_MISSING_SECRET, READINESS_SERVER_INACTIVE, RESOURCE_TYPE
from .mcp_capability_decisions import decide_mcp_capability
from .mcp_governance.capability_policy import load_mcp_capability_index, normalized_mcp_server_name
from .mcp_server_registry_config import resolved_runtime_config

_OWNER_SCOPES = {MCP_OWNER_PLATFORM, MCP_OWNER_WORKSPACE}


@dataclass(frozen=True, slots=True)
class McpServerReadiness:
    ready: bool
    reason: str
    capability_state: str
    config: MCPServerConfig | None = None

    def public(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "capability_governance": self.capability_state,
        }


def _normalize_owner(owner_scope: Any, workspace_id: Any) -> tuple[str, str | None]:
    owner = str(owner_scope or "").strip().lower()
    owner_workspace = str(workspace_id or "").strip() or None
    if owner not in _OWNER_SCOPES:
        raise HTTPException(status_code=400, detail="owner_scope must be 'workspace' or 'platform'")
    if owner == MCP_OWNER_WORKSPACE and not owner_workspace:
        raise HTTPException(status_code=400, detail="workspace ownership requires workspace_id")
    if owner == MCP_OWNER_PLATFORM and owner_workspace:
        raise HTTPException(status_code=400, detail="platform ownership must not include workspace_id")
    return owner, owner_workspace


async def _require_workspace(db: AsyncSession, workspace_id: str) -> Project:
    normalized = str(workspace_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    workspace = await db.get(Project, normalized)
    if workspace is None or not workspace.is_active:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _registration_query(name: str, workspace_id: str):
    return (
        select(McpServerRegistration)
        .options(selectinload(McpServerRegistration.secret_bindings))
        .where(
            McpServerRegistration.canonical_name == normalized_mcp_server_name(name),
            or_(
                McpServerRegistration.owner_scope == MCP_OWNER_PLATFORM,
                McpServerRegistration.workspace_id == workspace_id,
            ),
        )
        .order_by(
            case((McpServerRegistration.workspace_id == workspace_id, 0), else_=1),
            McpServerRegistration.name.asc(),
        )
    )


async def get_scoped_registration(
    db: AsyncSession,
    *,
    name: str,
    workspace_id: str,
) -> McpServerRegistration:
    # Cross-Workspace rows are hidden.
    await _require_workspace(db, workspace_id)
    registration = (await db.execute(_registration_query(name, workspace_id))).scalars().first()
    if registration is None:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' is not registered for this workspace")
    return registration


async def _audit_change(
    db: AsyncSession,
    *,
    registration: McpServerRegistration,
    actor_user_id: str | None,
    action: str,
    event_type: str = AUDIT_ADMIN_CHANGE,
    outcome: str = OUTCOME_ALLOWED,
) -> None:
    await create_audit_record(
        db,
        event_type=event_type,
        outcome=outcome,
        resource_type=RESOURCE_TYPE,
        resource_id=registration.id,
        resource_name=registration.name,
        actor_user_id=actor_user_id,
        actor_role="admin" if actor_user_id else None,
        project_id=registration.workspace_id,
        details={
            "action": action,
            "owner_scope": registration.owner_scope,
            "revision": registration.revision,
            "credential_binding_count": len(registration.secret_bindings),
        },
        commit=False,
    )


async def get_registration_by_id(db: AsyncSession, registration_id: str) -> McpServerRegistration:
    row = (
        await db.execute(
            select(McpServerRegistration)
            .options(selectinload(McpServerRegistration.secret_bindings))
            .where(McpServerRegistration.id == registration_id)
        )
    ).scalar_one()
    return row


async def _server_capability_state(db: AsyncSession, *, workspace_id: str, server_name: str) -> str:
    # Informational, never blocks a connection: every tool call is still decided per capability.
    index = await load_mcp_capability_index(db, workspace_id=workspace_id)
    normalized = normalized_mcp_server_name(server_name)
    for (server, tool_name), _capability in index.capabilities.items():
        if server == normalized and decide_mcp_capability(index, server_name=server_name, tool_name=tool_name).allowed:
            return "enabled_capability_present"
    return "no_enabled_capability"


async def mcp_server_readiness(
    db: AsyncSession,
    *,
    name: str,
    workspace_id: str,
    catalog: dict[str, dict[str, Any]],
) -> tuple[McpServerRegistration, McpServerReadiness]:
    registration = await get_scoped_registration(db, name=name, workspace_id=workspace_id)
    workspace = await _require_workspace(db, workspace_id)
    if not registration.is_active:
        return registration, McpServerReadiness(False, READINESS_SERVER_INACTIVE, "not_evaluated")
    access = mcp_server_access_decision(registration.name, workspace.config)
    if not access.allowed:
        return registration, McpServerReadiness(False, access.reason, "not_evaluated")
    capability_state = await _server_capability_state(db, workspace_id=workspace_id, server_name=registration.name)
    config = await resolved_runtime_config(db, registration=registration, catalog=catalog)
    if config is None:
        return registration, McpServerReadiness(False, READINESS_MISSING_SECRET, capability_state)
    return registration, McpServerReadiness(True, "ready", capability_state, config)
