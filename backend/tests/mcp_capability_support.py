"""Shared fixtures for the mirrored MCP capability governance suites.

The governance contract is tested from four angles — mirror writes
(``test_mcp_capability_mirror``), dispatch and discovery decisions
(``test_mcp_capability_dispatch``), approval identity
(``test_mcp_capability_approval``), and admin edits
(``test_mcp_capability_admin_write``) — and they all need the same workspace,
session, fake MCP client, and mirror helpers. They live here so each suite
carries only its own assertions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.models import McpServerRegistration, Project, User, WorkspaceCapabilityBinding
from app.models import Session as AgentSession
from app.plugins.mcp.models import MCPTool
from app.services.mcp_capability_catalog import mirror_mcp_server_capabilities
from app.services.mcp_capability_policy import mcp_capability_binding_key
from app.tools.context import ToolContext

SERVER = "demo"
READ_TOOL = "read_doc"
WRITE_TOOL = "write_doc"
DIRECT_READ_TOOL = f"mcp__{SERVER}__{READ_TOOL}"
DIRECT_WRITE_TOOL = f"mcp__{SERVER}__{WRITE_TOOL}"
BRIDGE_TOOL = "call_mcp_server_tool"

__all__ = [
    "BRIDGE_TOOL",
    "DIRECT_READ_TOOL",
    "DIRECT_WRITE_TOOL",
    "McpWorkspace",
    "READ_TOOL",
    "RecordingMcpManager",
    "SERVER",
    "WRITE_TOOL",
    "capability_binding",
    "create_mcp_workspace",
    "enable_capability",
    "install_mcp_manager",
    "mcp_tool",
    "mirror_tools",
    "register_mcp_server",
]


class RecordingMcpManager:
    """Fake MCP client that records every remote dispatch attempt."""

    def __init__(self, tools: list[MCPTool] | None = None) -> None:
        self._tools = list(tools or [])
        self.calls: list[tuple[str, str, dict]] = []
        self.connects: list[str] = []
        self._connected: set[str] = set()
        self._servers: dict[str, Any] = {}

    def get_server(self, name: str) -> object | None:
        return self._servers.get(name)

    def register_server(self, config: Any) -> None:
        self._servers[config.name] = config

    def unregister_server(self, name: str) -> None:
        self._servers.pop(name, None)
        self._connected.discard(name)

    async def is_connected(self, name: str) -> bool:
        return name in self._connected

    async def connect(self, name: str) -> bool:
        self.connects.append(name)
        self._connected.add(name)
        return True

    async def disconnect(self, name: str) -> bool:
        self._connected.discard(name)
        return True

    def get_tools(self, name: str) -> list[MCPTool]:
        return list(self._tools)

    async def call_tool(self, name: str, tool_name: str, arguments: dict) -> dict:
        self.calls.append((name, tool_name, dict(arguments)))
        return {"success": True, "content": [{"type": "text", "text": "ok"}]}


def install_mcp_manager(monkeypatch, manager: RecordingMcpManager) -> RecordingMcpManager:
    """Point every lazy ``mcp_client_manager`` import at the recording fake."""
    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", manager)
    return manager


def mcp_tool(name: str, description: str = "", properties: dict | None = None) -> MCPTool:
    return MCPTool(
        name=name,
        description=description or f"{name} description",
        input_schema={
            "type": "object",
            "properties": properties if properties is not None else {"path": {"type": "string"}},
            "required": ["path"] if properties is None else [],
        },
        server_name=SERVER,
        server_id=SERVER,
    )


@dataclass(frozen=True, slots=True)
class McpWorkspace:
    """One workspace plus the session identity its tool contexts run under."""

    project: Project
    user: User
    session: AgentSession

    def context(self, db, *, approval_policy: dict | None = None) -> ToolContext:
        """A chat-turn context: the active project comes from ``project_config``."""
        project_config: dict[str, Any] = {
            "project_id": self.project.id,
            "mcp_policy": {"enabled_servers": [SERVER]},
        }
        if approval_policy is not None:
            project_config["approval_policy"] = approval_policy
        return ToolContext(
            user_id=self.user.id,
            project_ids=[self.project.id],
            roles=["member"],
            session_id=self.session.id,
            project_config=project_config,
            db=db,
        )

    def flow_context(self, db) -> ToolContext:
        """A ToolContext exactly as the flow/DAG and flow-evidence owners build it.

        ``services/flow_orchestration/dag/tool_node.py`` and
        ``services/flow_orchestration/flow_evidence.py`` pass the caller's single
        project through ``project_ids`` and hand the raw project config through,
        which carries ``mcp_policy`` but no ``project_id``.
        """
        return ToolContext(
            user_id=self.user.id,
            project_ids=[self.project.id],
            roles=[],
            session_id=self.session.id,
            project_config={"mcp_policy": {"enabled_servers": [SERVER]}},
            db=db,
        )

    def unverifiable_context(self, db, *, project_ids: list[str]) -> ToolContext:
        """A context with no project id, or several competing ones."""
        return ToolContext(
            user_id=self.user.id,
            project_ids=project_ids,
            roles=["member"],
            session_id=self.session.id,
            project_config={"mcp_policy": {"enabled_servers": [SERVER]}},
            db=db,
        )


async def create_mcp_workspace(db) -> McpWorkspace:
    project = Project(id=str(uuid.uuid4()), name=f"mcp-capability-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(project)
    await db.flush()
    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(
        id=f"mcp-capability-{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
    )
    db.add(session)
    await db.flush()
    return McpWorkspace(project=project, user=user, session=session)


async def mirror_tools(
    db,
    workspace: McpWorkspace,
    tools: list[Any],
    *,
    server_name: str = SERVER,
) -> dict[str, Any]:
    """Mirror tool names (or ready-made ``MCPTool`` objects) for one workspace."""
    await register_mcp_server(db, workspace, server_name=server_name)
    return await mirror_mcp_server_capabilities(
        db,
        workspace_id=workspace.project.id,
        server_name=server_name,
        tools=[mcp_tool(tool) if isinstance(tool, str) else tool for tool in tools],
    )


async def register_mcp_server(db, workspace: McpWorkspace, *, server_name: str = SERVER) -> McpServerRegistration:
    """Persist the active registry prerequisite without creating mirror history."""
    existing = (
        await db.execute(
            select(McpServerRegistration).where(
                McpServerRegistration.workspace_id == workspace.project.id,
                McpServerRegistration.canonical_name == server_name.casefold(),
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = McpServerRegistration(
            name=server_name,
            owner_scope="workspace",
            workspace_id=workspace.project.id,
            transport="streamable-http",
            url="https://example.test/mcp",
            args_json=[],
            settings_json={},
            is_active=True,
        )
        db.add(existing)
    workspace.project.config = {
        **(workspace.project.config or {}),
        "mcp_policy": {"enabled_servers": [server_name]},
    }
    await db.flush()
    return existing


async def capability_binding(
    db,
    workspace: McpWorkspace,
    tool_name: str,
    *,
    server_name: str = SERVER,
) -> WorkspaceCapabilityBinding:
    return (
        await db.execute(
            select(WorkspaceCapabilityBinding).where(
                WorkspaceCapabilityBinding.workspace_id == workspace.project.id,
                WorkspaceCapabilityBinding.binding_key == mcp_capability_binding_key(server_name, tool_name),
            )
        )
    ).scalar_one()


async def enable_capability(
    db,
    workspace: McpWorkspace,
    tool_name: str,
    *,
    risk: str,
    server_name: str = SERVER,
) -> WorkspaceCapabilityBinding:
    binding = await capability_binding(db, workspace, tool_name, server_name=server_name)
    binding.is_enabled = True
    binding.policy_config = {**(binding.policy_config or {}), "risk": risk}
    await db.flush()
    return binding
