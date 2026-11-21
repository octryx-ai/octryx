from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import McpServerRegistration, Project, WorkspaceCapabilityBinding
from app.plugins.mcp.models import MCPTool
from app.services.mcp_capability_catalog import mirror_mcp_server_capabilities
from app.services.mcp_capability_policy import mcp_capability_binding_key
from app.tools.context import ToolContext
from app.tools.registry import execute_tool_with_plugins


async def _workspace(db) -> Project:
    """A verifiable workspace whose ``context7`` server has its ``resolve-library-id`` tool mirrored and enabled."""
    project = Project(
        id=str(uuid.uuid4()),
        name=f"mcp-acceptance-{uuid.uuid4().hex[:6]}",
        config={"mcp_policy": {"enabled_servers": ["context7"]}},
        is_active=True,
    )
    db.add(project)
    await db.flush()
    db.add(
        McpServerRegistration(
            name="context7",
            owner_scope="workspace",
            workspace_id=project.id,
            transport="streamable-http",
            url="https://example.test/mcp",
            args_json=[],
            settings_json={},
            is_active=True,
        )
    )
    await db.flush()
    await mirror_mcp_server_capabilities(db, workspace_id=project.id, server_name="context7", tools=[MCPTool(
        name="resolve-library-id", description="Resolve a library id",
        input_schema={"type": "object", "properties": {"libraryName": {"type": "string"}}},
        server_name="context7", server_id="context7")])
    binding = (await db.execute(select(WorkspaceCapabilityBinding).where(
        WorkspaceCapabilityBinding.workspace_id == project.id,
        WorkspaceCapabilityBinding.binding_key == mcp_capability_binding_key("context7", "resolve-library-id"),
    ))).scalar_one()
    binding.is_enabled = True
    binding.policy_config = {**binding.policy_config, "risk": "read"}
    await db.flush()
    return project


class _RegistryAwareFake:
    def __init__(self) -> None:
        self._servers = {}
        self._connected = set()

    def get_server(self, name):
        return self._servers.get(name)

    def register_server(self, config):
        self._servers[config.name] = config

    def unregister_server(self, name):
        self._servers.pop(name, None)
        self._connected.discard(name)

    async def is_connected(self, name):
        return name in self._connected

    async def connect(self, name):
        self._connected.add(name)
        return True

    async def disconnect(self, name):
        self._connected.discard(name)
        return True

    def get_tools(self, name):
        return []


def _context(db=None, project: Project | None = None, project_config: dict | None = None) -> ToolContext:
    config = dict(project_config or {})
    if project is not None:
        config["project_id"] = project.id
    return ToolContext(
        user_id="user-1",
        project_ids=[project.id] if project is not None else ["project-1"],
        roles=["admin"],
        session_id="session-1",
        project_config=config,
        db=db,
        workspace_root="/tmp/workspace",
    )


@pytest.mark.asyncio
async def test_mcp_acceptance_disabled_by_default_denies_direct_execution(monkeypatch) -> None:
    class FakeManager:
        called = False

        async def call_tool(self, _server_name, _tool_name, _params):
            self.called = True
            return {"success": True}

    fake_manager = FakeManager()
    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", fake_manager)

    result = await execute_tool_with_plugins("mcp__github__create_issue", {}, _context())

    assert result["blocked_by"] == "mcp_access_policy"
    assert result["tool_execution"]["category"] == "denied_by_policy"
    assert fake_manager.called is False


@pytest.mark.asyncio
async def test_mcp_acceptance_configured_but_inactive_server_is_typed(db, monkeypatch) -> None:
    class FakeManager(_RegistryAwareFake):
        async def connect(self, name):
            return False

        async def call_tool(self, server_name, tool_name, _params):
            return {
                "error": f"Not connected to MCP server '{server_name}'",
                "mcp_server": server_name,
                "mcp_tool": tool_name,
                "source": "mcp",
                "error_category": "inactive_server",
                "reason": "mcp_server_not_connected",
            }

    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", FakeManager())

    result = await execute_tool_with_plugins(
        "mcp__context7__resolve-library-id",
        {"libraryName": "react"},
        _context(db, await _workspace(db), {"mcp_policy": {"enabled_servers": ["context7"]}}),
    )

    assert result["tool_execution"]["category"] == "inactive_server"
    assert result["tool_execution"]["reason"] == "mcp_registry_connection_denied"
    assert result["tool_execution"]["policy"] == "mcp_access_policy"


@pytest.mark.asyncio
async def test_mcp_acceptance_active_safe_server_executes(db, monkeypatch) -> None:
    class FakeManager(_RegistryAwareFake):
        async def call_tool(self, server_name, tool_name, params):
            assert server_name == "context7"
            assert tool_name == "resolve-library-id"
            assert params == {"libraryName": "react"}
            return {"success": True, "content": [{"type": "text", "text": "/facebook/react"}]}

    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", FakeManager())

    result = await execute_tool_with_plugins(
        "mcp__context7__resolve-library-id",
        {"libraryName": "react"},
        _context(db, await _workspace(db), {"mcp_policy": {"enabled_servers": ["context7"]}}),
    )

    assert result == {"success": True, "content": [{"type": "text", "text": "/facebook/react"}]}


@pytest.mark.asyncio
async def test_mcp_acceptance_invalid_direct_tool_name_is_typed() -> None:
    result = await execute_tool_with_plugins(
        "mcp__context7",
        {},
        _context(project_config={"mcp_policy": {"enabled_servers": ["context7"]}}),
    )

    assert result["tool_execution"]["category"] == "invalid_name"
    assert result["tool_execution"]["reason"] == "invalid_mcp_tool_name"


@pytest.mark.asyncio
async def test_mcp_acceptance_execution_failure_is_typed_and_redacted(db, monkeypatch) -> None:
    class FakeManager(_RegistryAwareFake):
        async def call_tool(self, _server_name, _tool_name, _params):
            raise RuntimeError("provider failed with token=abc1" + "23456789")

    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", FakeManager())

    result = await execute_tool_with_plugins(
        "mcp__context7__resolve-library-id",
        {},
        _context(db, await _workspace(db), {"mcp_policy": {"enabled_servers": ["context7"]}}),
    )

    assert result["tool_execution"]["category"] == "provider_failure"
    assert result["tool_execution"]["reason"] == "mcp_tool_execution_failed"
    assert ("abc1" + "23456789") not in result["error"]
    assert "token=[redacted]" in result["error"]
