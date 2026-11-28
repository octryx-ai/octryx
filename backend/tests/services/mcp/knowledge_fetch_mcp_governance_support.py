"""Shared recording MCP manager, workspace, session and capability helpers for the fetch_and_save_knowledge MCP governance tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import McpServerRegistration, Project, User, WorkspaceCapabilityBinding
from app.models import Session as AgentSession
from app.plugins.mcp.models import MCPTool
from app.services.mcp_governance.capability_policy import mcp_capability_binding_key
from app.tools.context import ToolContext
from tests.factories import make_project

SERVER = "demo"


CONTEXT7_RESOLVE = "resolve-library-id"


class _RecordingMcpManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        # Outbound connection attempts: a denied capability must produce none.
        self.connects: list[str] = []
        self._connected: set[str] = set()
        self._servers: dict[str, object] = {}

    async def is_connected(self, name: str) -> bool:
        return name in self._connected

    async def connect(self, name: str) -> bool:
        self.connects.append(name)
        self._connected.add(name)
        return True

    def register_server(self, config) -> None:
        self._servers[config.name] = config

    def get_server(self, name: str):
        return self._servers.get(name)

    def unregister_server(self, name: str) -> None:
        self._servers.pop(name, None)

    def get_tools(self, name: str) -> list:
        return []

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> dict:
        self.calls.append((server_name, tool_name, dict(arguments)))
        if tool_name == CONTEXT7_RESOLVE:
            return {"content": [{"type": "text", "text": "/facebook/react"}]}
        return {"content": [{"type": "text", "text": "remote documentation body"}]}


def _mcp_tool(name: str) -> MCPTool:
    return MCPTool(
        name=name,
        description=f"{name} description",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": []},
        server_name=SERVER,
        server_id=SERVER,
    )


async def _workspace(db) -> Project:
    return await make_project(db, name=f"knowledge-mcp-{uuid.uuid4().hex[:6]}")


async def _session(db, project: Project) -> tuple[User, AgentSession]:
    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(
        id=f"knowledge-mcp-{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
    )
    db.add(session)
    await db.flush()
    return user, session


def _context(
    *,
    db,
    user: User,
    session: AgentSession,
    project: Project,
    enabled_servers: list[str],
    approval_policy: dict | None = None,
) -> ToolContext:
    project_config: dict = {
        "project_id": project.id,
        "mcp_policy": {"enabled_servers": enabled_servers},
    }
    if approval_policy is not None:
        project_config["approval_policy"] = approval_policy
    project.config = project_config
    return ToolContext(
        user_id=user.id,
        project_ids=[project.id],
        roles=["member"],
        session_id=session.id,
        project_config=project_config,
        db=db,
    )


async def _enable(db, project: Project, server: str, tool_name: str, *, risk: str) -> None:
    binding = (
        await db.execute(
            select(WorkspaceCapabilityBinding).where(
                WorkspaceCapabilityBinding.workspace_id == project.id,
                WorkspaceCapabilityBinding.binding_key == mcp_capability_binding_key(server, tool_name),
            )
        )
    ).scalar_one()
    binding.is_enabled = True
    binding.policy_config = {**(binding.policy_config or {}), "risk": risk}
    registration = (
        await db.execute(select(McpServerRegistration).where(McpServerRegistration.name == server))
    ).scalar_one_or_none()
    if registration is None:
        db.add(
            McpServerRegistration(
                name=server,
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


def _install(monkeypatch, manager: _RecordingMcpManager) -> None:
    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", manager)
