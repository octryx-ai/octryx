"""Shared fixtures for the governed MCP resource/prompt suites.

The contract is tested from four angles — mirror writes
(``test_mcp_resource_mirror``), dispatch and discovery decisions
(``test_mcp_resource_dispatch``), audit evidence (``test_mcp_resource_audit``),
and admin edits (``test_mcp_resource_admin_write``) — and they all need the same
workspace, tool contexts, fake MCP client, and mirror helpers.

The workspace/session fixture is reused from ``mcp_capability_support`` so both MCP
governance surfaces run against exactly the same workspace shape. The contexts are
built here because the resource gate also reads the run's execution scope
(``capability_type`` / ``agent_mode_key``), which the capability suites do not use.
The recording fake MCP client lives in ``mcp_resource_client_support``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import McpServerRegistration, WorkspaceCapabilityBinding
from app.plugins.mcp.models import MCPPrompt, MCPResource
from app.services.mcp_resource_catalog import mirror_mcp_server_resources
from app.services.mcp_resource_identity import (
    governed_mcp_resource_uri,
    mcp_prompt_binding_key,
    mcp_resource_binding_key,
    mcp_resource_identity_digest,
)
from app.tools.context import ToolContext
from tests.mcp_capability_support import McpWorkspace, create_mcp_workspace

SERVER = "demo"
DOC_URI = "docs://react"
OTHER_URI = "docs://vue"
# URIs that carry a credential. None of them may ever be mirrored, addressed,
# persisted, or forwarded: the userinfo form is what ``redact_secret_text``
# already caught, the ``postgres://`` and presign forms are the two it does not.
SECRET_URI = "https://svc:s3cr3t-token@internal.example/report.json"
POSTGRES_URI = "postgres://admin:s3cr3t-token@db.internal/reports"
PRESIGNED_URI = "https://bucket.s3.eu-central-1.amazonaws.com/r.json?X-Amz-Signature=s3cr3t-token&X-Amz-Expires=60"
CREDENTIAL_URIS = (SECRET_URI, POSTGRES_URI, PRESIGNED_URI)
PROMPT = "summarize-docs"
OTHER_PROMPT = "review-docs"

LIST_RESOURCES_TOOL = "list_mcp_server_resources"
READ_RESOURCE_TOOL = "read_mcp_server_resource"
LIST_PROMPTS_TOOL = "list_mcp_server_prompts"
GET_PROMPT_TOOL = "get_mcp_server_prompt"

__all__ = [
    "CREDENTIAL_URIS",
    "DOC_URI",
    "GET_PROMPT_TOOL",
    "LIST_PROMPTS_TOOL",
    "LIST_RESOURCES_TOOL",
    "OTHER_PROMPT",
    "OTHER_URI",
    "POSTGRES_URI",
    "PRESIGNED_URI",
    "PROMPT",
    "READ_RESOURCE_TOOL",
    "SECRET_URI",
    "SERVER",
    "McpWorkspace",
    "create_mcp_workspace",
    "enable_binding",
    "mcp_prompt",
    "mcp_resource",
    "mirror_catalog",
    "prompt_binding",
    "register_mcp_server",
    "read_params",
    "resource_binding",
    "resource_id",
    "resource_context",
    "unverifiable_context",
]


def mcp_resource(uri: str, *, name: str = "", description: str = "", mime_type: str = "text/markdown") -> MCPResource:
    return MCPResource(
        uri=uri,
        name=name or uri.rsplit("/", 1)[-1],
        description=description or f"{uri} description",
        mime_type=mime_type,
        server_name=SERVER,
        server_id=SERVER,
    )


def mcp_prompt(name: str, *, description: str = "", arguments: list[dict] | None = None) -> MCPPrompt:
    return MCPPrompt(
        name=name,
        description=description or f"{name} description",
        arguments=[{"name": "topic", "description": "Topic name", "required": True}]
        if arguments is None
        else arguments,
        server_name=SERVER,
        server_id=SERVER,
    )


def resource_context(
    workspace: McpWorkspace,
    db,
    *,
    approval_policy: dict | None = None,
    capability_type: str | None = "diagnosis",
    agent_mode_key: str | None = None,
    enabled_servers: list[str] | None = None,
) -> ToolContext:
    """A chat-turn context: the active project comes from ``project_config``."""
    project_config: dict[str, Any] = {
        "project_id": workspace.project.id,
        "mcp_policy": {"enabled_servers": [SERVER] if enabled_servers is None else enabled_servers},
    }
    if approval_policy is not None:
        project_config["approval_policy"] = approval_policy
    return ToolContext(
        user_id=workspace.user.id,
        project_ids=[workspace.project.id],
        roles=["member"],
        session_id=workspace.session.id,
        project_config=project_config,
        db=db,
        capability_type=capability_type,
        agent_mode_key=agent_mode_key,
    )


def unverifiable_context(
    workspace: McpWorkspace,
    db,
    *,
    project_ids: list[str] | None = None,
    user_id: str | None = None,
) -> ToolContext:
    """A context with no project id, or several competing ones."""
    return ToolContext(
        user_id=workspace.user.id if user_id is None else user_id,
        project_ids=[] if project_ids is None else project_ids,
        roles=["member"],
        session_id=workspace.session.id,
        project_config={"mcp_policy": {"enabled_servers": [SERVER]}},
        db=db,
        capability_type="diagnosis",
    )


async def mirror_catalog(
    db,
    workspace: McpWorkspace,
    *,
    resources: list[Any] | None = None,
    prompts: list[Any] | None = None,
    server_name: str = SERVER,
) -> dict[str, Any]:
    """Mirror resource URIs/objects and prompt names/objects for one workspace."""
    await register_mcp_server(db, workspace, server_name=server_name)
    return await mirror_mcp_server_resources(
        db,
        workspace_id=workspace.project.id,
        server_name=server_name,
        resources=[mcp_resource(item) if isinstance(item, str) else item for item in (resources or [])],
        prompts=[mcp_prompt(item) if isinstance(item, str) else item for item in (prompts or [])],
    )


async def register_mcp_server(db, workspace: McpWorkspace, *, server_name: str = SERVER) -> McpServerRegistration:
    """Persist the scoped server prerequisite without changing its mirrored catalog."""
    existing = (
        await db.execute(
            select(McpServerRegistration).where(
                McpServerRegistration.name == server_name,
                McpServerRegistration.workspace_id == workspace.project.id,
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


def resource_id(uri: str, *, server_name: str = SERVER) -> str:
    """The opaque governed identity a model addresses this resource by."""
    return mcp_resource_identity_digest(server_name, governed_mcp_resource_uri(uri))


def read_params(uri: str = DOC_URI, *, server_name: str = SERVER) -> dict[str, Any]:
    """A ``read_mcp_server_resource`` request; there is no URI channel."""
    return {"server_name": server_name, "resource_id": resource_id(uri, server_name=server_name)}


async def _binding(db, workspace: McpWorkspace, binding_key: str) -> WorkspaceCapabilityBinding:
    return (
        await db.execute(
            select(WorkspaceCapabilityBinding)
            .options(selectinload(WorkspaceCapabilityBinding.capability_type))
            .where(
                WorkspaceCapabilityBinding.workspace_id == workspace.project.id,
                WorkspaceCapabilityBinding.binding_key == binding_key,
            )
        )
    ).scalar_one()


async def resource_binding(
    db,
    workspace: McpWorkspace,
    uri: str,
    *,
    server_name: str = SERVER,
) -> WorkspaceCapabilityBinding:
    return await _binding(db, workspace, mcp_resource_binding_key(server_name, resource_id(uri, server_name=server_name)))


async def prompt_binding(
    db,
    workspace: McpWorkspace,
    prompt_name: str,
    *,
    server_name: str = SERVER,
) -> WorkspaceCapabilityBinding:
    return await _binding(db, workspace, mcp_prompt_binding_key(server_name, prompt_name))


async def enable_binding(
    db,
    binding: WorkspaceCapabilityBinding,
    *,
    risk: str = "read",
    scopes: list[str] | None = None,
) -> WorkspaceCapabilityBinding:
    binding.is_enabled = True
    binding.policy_config = {**(binding.policy_config or {}), "risk": risk}
    if scopes is not None:
        binding.intent_scopes = scopes
    await db.flush()
    return binding
