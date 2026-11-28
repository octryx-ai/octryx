"""Approval is keyed to the resource and enforced on direct execution, one dispatch consumes one grant, and credential, identity and server-configuration faults deny before the transport is reached."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, McpServerRegistration
from app.services.mcp_governance.resource_audit import MCP_RESOURCE_AUDIT_ACTION
from app.services.mcp_governance.resource_identity import MCP_RESOURCE_POLICY_NAME, mcp_resource_subject_key
from app.services.mcp_governance.resource_states import STATE_UNKNOWN_SERVER
from app.tools.mcp_resource_bridge import GetMcpServerPromptTool, ReadMcpServerResourceTool
from app.tools.registry import execute_tool_with_plugins
from tests.services.mcp_governance.mcp_resource_dispatch_support import _enabled_resource_workspace, _get
from tests.support.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.support.mcp_resource_support import (
    CREDENTIAL_URIS,
    DOC_URI,
    GET_PROMPT_TOOL,
    LIST_RESOURCES_TOOL,
    READ_RESOURCE_TOOL,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mirror_catalog,
    read_params,
    resource_binding,
    resource_context,
    resource_id,
)


async def _resource_audit_states(db, workspace) -> list[str]:
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.action == MCP_RESOURCE_AUDIT_ACTION)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    return [row.details["state"] for row in rows if row.details.get("workspace_id") == workspace.project.id]


@pytest.mark.asyncio
async def test_approval_identity_is_the_resource_not_the_bridge_tool(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch, risk="write")
    context = resource_context(workspace, db, approval_policy={"require_for_risks": ["write"]})
    identity = await resource_binding(db, workspace, DOC_URI)

    listing = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
    read = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)

    assert listing["resources"][0]["approval_required"] is True
    assert read["approval_required"] is True
    assert read["blocked_by"] == "tool_approval_gate"
    assert read["approval_subject"] == mcp_resource_subject_key(
        "mcp_resource", SERVER, identity.binding_config["resourceIdentity"]
    )
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_direct_execution_enforces_the_same_approval_before_connecting(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch, risk="write")
    context = resource_context(workspace, db, approval_policy={"require_for_risks": ["write"]})

    read = await ReadMcpServerResourceTool().execute(read_params(), context)
    rendered = await GetMcpServerPromptTool().execute(_get(), context)

    for result in (read, rendered):
        assert result["approval_required"] is True
        assert result["blocked_by"] == "tool_approval_gate"
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_one_registry_dispatch_consumes_exactly_one_approval_grant(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch, risk="write")
    context = resource_context(workspace, db, approval_policy={"require_for_risks": ["write"]})
    context.enforced_approval_fingerprints.clear()

    held = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)

    assert held["approval_required"] is True
    assert context.enforced_approval_fingerprints == set()
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_a_credential_bearing_resource_denies_before_transport(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[*CREDENTIAL_URIS, DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    context = resource_context(workspace, db)

    results = [
        await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(uri), context) for uri in CREDENTIAL_URIS
    ]
    listing = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)

    for result in results:
        assert result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
        assert result["reason"] == "mcp_resource_not_available"
    assert "s3cr3t-token" not in str(results) + str(listing)
    assert [entry["resource_id"] for entry in listing["resources"]] == [resource_id(DOC_URI)]
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_a_request_without_an_item_identity_is_denied_like_an_unknown_item(db, monkeypatch) -> None:
    workspace, manager = await _enabled_resource_workspace(db, monkeypatch)
    context = resource_context(workspace, db)

    no_id = await execute_tool_with_plugins(READ_RESOURCE_TOOL, {"server_name": SERVER}, context)
    a_uri_instead = await execute_tool_with_plugins(
        READ_RESOURCE_TOOL, {"server_name": SERVER, "resource_id": DOC_URI}, context
    )
    no_prompt = await execute_tool_with_plugins(GET_PROMPT_TOOL, {"server_name": SERVER}, context)
    no_server = await execute_tool_with_plugins(READ_RESOURCE_TOOL, {"resource_id": resource_id(DOC_URI)}, context)
    unknown = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params("docs://never-mirrored"), context)

    assert no_id == a_uri_instead == unknown
    assert no_prompt["reason"] == "mcp_prompt_not_available"
    assert no_server["blocked_by"] == "mcp_access_policy"
    assert no_server["reason"] == "missing_server_name"
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_legacy_runtime_case_collision_cannot_retarget_the_persisted_server(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(
        monkeypatch, RecordingMcpResourceManager(configured_servers=[SERVER, SERVER.upper()])
    )
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    context = resource_context(workspace, db, enabled_servers=[SERVER, SERVER.upper()])

    lower = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)
    upper = await execute_tool_with_plugins(
        READ_RESOURCE_TOOL, {"server_name": SERVER.upper(), "resource_id": resource_id(DOC_URI)}, context
    )

    assert lower["contents"][0]["text"] == "# React"
    assert upper["contents"][0]["text"] == "# React"
    assert manager.resource_reads == [(SERVER, DOC_URI), (SERVER, DOC_URI)]


@pytest.mark.asyncio
async def test_a_server_no_longer_configured_denies_before_connect(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager(configured_servers=[]))
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    registration = (
        await db.execute(select(McpServerRegistration).where(McpServerRegistration.name == SERVER))
    ).scalar_one()
    await db.delete(registration)
    await db.flush()

    result = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))

    assert result["reason"] == "mcp_resource_not_available"
    assert manager.touched_remote is False
    assert await _resource_audit_states(db, workspace) == [STATE_UNKNOWN_SERVER]


@pytest.mark.asyncio
async def test_the_transport_is_called_with_the_one_configured_server_name(db, monkeypatch) -> None:
    configured = "Demo"
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager(configured_servers=[configured]))
    await mirror_catalog(db, workspace, resources=[DOC_URI], server_name=configured)
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI, server_name=configured))

    result = await execute_tool_with_plugins(
        READ_RESOURCE_TOOL,
        {"server_name": SERVER, "resource_id": resource_id(DOC_URI, server_name=configured)},
        resource_context(workspace, db),
    )

    assert result["contents"][0]["text"] == "# React"
    # The model asked for ``demo``; the catalog and the transport both resolved to
    # the single configured spelling instead of trusting the request.
    assert manager.connects == [configured]
    assert manager.resource_reads == [(configured, DOC_URI)]
    assert result["server_name"] == configured
