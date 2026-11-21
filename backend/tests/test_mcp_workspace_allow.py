"""Allow an MCP server per Workspace: the first writer of ``mcp_policy``, with tool selection."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import AuditLog, McpServerRegistration, Project, User
from app.services.auth import create_access_token
from app.services.mcp_access_policy import mcp_server_access_decision, mcp_tool_allowed
from app.services.mcp_workspace_allow import (
    McpAllowError,
    allow_status,
    apply_server_allow,
    server_allow,
    set_server_allow,
    set_workspace_server,
)


class Manager:
    """Every registration is unconnected: the pipeline stops at "connected"."""

    async def is_connected(self, _name):
        return False

    def get_tools(self, _name):
        return [SimpleNamespace(name="search_tickets"), SimpleNamespace(name="get_ticket")]

    def get_server(self, _name):
        return None


def test_the_writer_allows_with_all_or_selected_tools_and_keeps_other_policy_keys():
    base = {"mcp_policy": {"enabled_servers": ["Other"], "disabled_servers": ["blocked"], "allow_all": False}}
    allowed = apply_server_allow(base, "Tickets", allowed=True, tools=None)
    selected = apply_server_allow(allowed, "Tickets", allowed=True, tools=["search_tickets"])
    removed = apply_server_allow(selected, "tickets", allowed=False, tools=None)

    assert mcp_server_access_decision("Tickets", allowed).allowed and mcp_tool_allowed("Tickets", "get_ticket", allowed)
    assert mcp_tool_allowed("Tickets", "search_tickets", selected) and not mcp_tool_allowed("Tickets", "get_ticket", selected)
    assert not mcp_server_access_decision("Tickets", removed).allowed
    assert removed["mcp_policy"]["enabled_servers"] == ["Other"] and "selected_tools" not in removed["mcp_policy"]
    assert removed["mcp_policy"]["disabled_servers"] == ["blocked"]


async def _server(db, *, owner: Project | None = None) -> McpServerRegistration:
    server = McpServerRegistration(
        name=f"tickets-{uuid.uuid4().hex[:6]}", owner_scope="workspace" if owner else "platform",
        workspace_id=owner.id if owner else None, transport="streamable-http", url="https://mcp.invalid/mcp",
        is_active=True,
    )
    db.add(server)
    await db.commit()
    return server


async def _workspace(db, name: str) -> Project:
    project = Project(id=str(uuid.uuid4()), name=name, is_active=True, config={})
    db.add(project)
    await db.commit()
    return project


@pytest.mark.asyncio
async def test_allowing_a_server_in_workspaces_is_stored_audited_and_counted(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    claims, finance = await _workspace(db, "Claims"), await _workspace(db, "Finance")
    server = await _server(db)

    await set_server_allow(db, server_id=server.id, workspace_ids=[claims.id], tools=["search_tickets"], actor_id=admin.id)
    await db.commit()
    detail = await server_allow(db, server_id=server.id, mcp_client_manager=Manager())
    status = next(row for row in await allow_status(db, mcp_client_manager=Manager()) if row["server_id"] == server.id)

    rows = {row["name"]: row for row in detail["workspaces"]}
    assert rows["Claims"]["allowed"] and rows["Claims"]["tools"] == ["search_tickets"]
    assert not rows["Finance"]["allowed"]
    assert (status["allowed_workspaces"], status["connected"], status["tools_visible"]) == (1, False, False)
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.mcp.workspace_allow_changed",
                                                      AuditLog.resource_id == claims.id))).scalars().all()
    assert len(audits) == 1

    await set_workspace_server(db, workspace_id=finance.id, server_id=server.id, allowed=True, actor_id=admin.id)
    await db.commit()
    await db.refresh(finance)
    assert mcp_server_access_decision(server.name, finance.config).allowed


@pytest.mark.asyncio
async def test_a_workspace_owned_server_is_allowed_only_in_its_own_workspace(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    owner, other = await _workspace(db, "Owner"), await _workspace(db, "Other")
    server = await _server(db, owner=owner)

    with pytest.raises(McpAllowError) as refused:
        await set_workspace_server(db, workspace_id=other.id, server_id=server.id, allowed=True, actor_id=admin.id)
    assert refused.value.code == "mcp_server_owned_by_another_workspace"
    with pytest.raises(McpAllowError):
        await set_server_allow(db, server_id=server.id, workspace_ids=[other.id], tools=None, actor_id=admin.id)


@pytest.mark.asyncio
async def test_the_api_is_for_platform_admins(client, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    claims_id = (await _workspace(db, "Claims API")).id
    server_id = (await _server(db)).id
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}

    saved = await client.put(f"/api/v1/admin/mcp-servers/{server_id}/allow",
                             json={"workspace_ids": [claims_id], "tools": None}, headers=headers)
    refused = await client.put(f"/api/v1/admin/mcp-servers/{server_id}/allow",
                               json={"workspace_ids": [claims_id], "tools": []}, headers=headers)
    toggled = await client.put(f"/api/v1/admin/workspaces/{claims_id}/mcp-servers/{server_id}",
                               json={"allowed": False}, headers=headers)

    assert saved.status_code == 200 and any(row["allowed"] for row in saved.json()["workspaces"])
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "mcp_tools_invalid"
    assert toggled.status_code == 200 and toggled.json()["allowed"] is False
    listed = (await client.get(f"/api/v1/admin/workspaces/{claims_id}/mcp-servers", headers=headers)).json()
    assert any(row["server_id"] == server_id and row["allowed"] is False for row in listed["servers"])
    assert (await client.get("/api/v1/admin/mcp-servers/allow")).status_code == 401
