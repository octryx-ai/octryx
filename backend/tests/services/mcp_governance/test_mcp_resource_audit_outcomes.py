"""Discovery, user-less contexts, transport failures and late policy changes each leave one truthful audit outcome."""

from __future__ import annotations

import pytest

from app.services.mcp_governance.resource_audit import (
    DISPATCH_DISCOVERY,
    DISPATCH_TOOL,
    OUTCOME_DENIED,
    OUTCOME_EXECUTED,
    OUTCOME_TRANSPORT_FAILED,
    OUTCOME_TRANSPORT_UNAVAILABLE,
)
from app.services.mcp_governance.resource_identity import MCP_RESOURCE_POLICY_NAME
from app.services.mcp_governance.resource_states import STATE_ALLOWED, STATE_DISABLED, STATE_MISSING_WORKSPACE
from app.tools.mcp_resource_bridge import ReadMcpServerResourceTool
from app.tools.registry import execute_tool_with_plugins
from tests.services.mcp_governance.mcp_resource_audit_support import _audit_rows
from tests.support.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.support.mcp_resource_support import (
    DOC_URI,
    LIST_RESOURCES_TOOL,
    READ_RESOURCE_TOOL,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mirror_catalog,
    read_params,
    resource_binding,
    resource_context,
    unverifiable_context,
)


def _refuse_to_connect(manager):
    async def connect(name: str) -> bool:
        manager.connects.append(name)
        return False

    return connect


@pytest.mark.asyncio
async def test_successful_and_empty_discovery_are_both_audited(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    context = resource_context(workspace, db)

    empty = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))
    visible = await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, context)

    rows = await _audit_rows(db, workspace)
    assert empty["count"] == 0 and visible["count"] == 1
    assert len(rows) == 2
    assert [row.details["discovery_state"] for row in rows] == ["no_visible_entries", "enforced"]
    assert [row.details["visible"] for row in rows] == [0, 1]
    assert [row.details["dispatch"] for row in rows] == [DISPATCH_DISCOVERY, DISPATCH_DISCOVERY]
    assert {row.details["outcome"] for row in rows} == {OUTCOME_EXECUTED}
    # Discovery evidence names counts, never the items themselves.
    assert "identity" not in rows[0].details


@pytest.mark.asyncio
async def test_blocked_discovery_is_audited_as_discovery(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    install_mcp_manager(monkeypatch, RecordingMcpResourceManager())

    await execute_tool_with_plugins(LIST_RESOURCES_TOOL, {"server_name": SERVER}, unverifiable_context(workspace, db))

    rows = await _audit_rows(db, workspace)
    assert len(rows) == 1
    assert rows[0].details["dispatch"] == DISPATCH_DISCOVERY
    assert rows[0].details["state"] == STATE_MISSING_WORKSPACE
    assert rows[0].details["outcome"] == OUTCOME_DENIED
    assert rows[0].details["public_reason"] == "mcp_resource_governance_unverifiable"


@pytest.mark.asyncio
async def test_a_context_without_a_user_still_denies_without_an_audit_row(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])

    result = await execute_tool_with_plugins(
        READ_RESOURCE_TOOL,
        read_params(),
        unverifiable_context(workspace, db, project_ids=[workspace.project.id], user_id=""),
    )

    assert result["reason"] == "mcp_resource_governance_unverifiable"
    assert result["blocked_by"] == MCP_RESOURCE_POLICY_NAME
    assert await _audit_rows(db, workspace) == []
    assert manager.touched_remote is False


@pytest.mark.asyncio
async def test_a_context_without_a_user_denies_an_enabled_item_needing_no_approval(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk="read")
    context = unverifiable_context(workspace, db, project_ids=[workspace.project.id], user_id="")

    dispatched = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), context)
    direct = await ReadMcpServerResourceTool().execute(read_params(), context)

    assert dispatched["reason"] == direct["reason"] == "mcp_resource_governance_unverifiable"
    # Both paths deny before transport, and neither leaves an allowed-but-unaudited trace.
    assert manager.touched_remote is False
    assert await _audit_rows(db, workspace) == []


@pytest.mark.asyncio
async def test_an_unreachable_transport_is_never_recorded_as_an_execution(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    monkeypatch.setattr(manager, "connect", _refuse_to_connect(manager))
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))

    result = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))

    rows = await _audit_rows(db, workspace)
    assert "not connected" in result["error"]
    assert manager.resource_reads == []
    # Exactly one row, and it says the transport failed rather than that the
    # request executed.
    assert len(rows) == 1
    assert rows[0].details["state"] == STATE_ALLOWED
    assert rows[0].details["outcome"] == OUTCOME_TRANSPORT_UNAVAILABLE
    assert rows[0].details["dispatch"] == DISPATCH_TOOL


@pytest.mark.asyncio
async def test_a_failing_remote_call_is_recorded_as_a_failure(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())

    async def failing_read(name: str, uri: str) -> dict:
        manager.resource_reads.append((name, uri))
        return {"error": "upstream refused"}

    monkeypatch.setattr(manager, "read_resource", failing_read)
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI))

    await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))

    rows = await _audit_rows(db, workspace)
    assert len(rows) == 1
    assert rows[0].details["outcome"] == OUTCOME_TRANSPORT_FAILED


@pytest.mark.asyncio
async def test_a_policy_change_after_the_gate_yields_one_truthful_denial(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI])
    binding = await enable_binding(db, await resource_binding(db, workspace, DOC_URI))

    import app.services.tool_approval.gate as approval_gate

    original = approval_gate.enforce_tool_approval

    async def disable_then_approve(tool_name, params, context, *, subject=None):
        # The admin disables the binding in the window between the registry's
        # decision and the tool's own pre-transport check.
        binding.is_enabled = False
        await db.flush()
        return await original(tool_name, params, context, subject=subject)

    monkeypatch.setattr(approval_gate, "enforce_tool_approval", disable_then_approve)

    result = await execute_tool_with_plugins(READ_RESOURCE_TOOL, read_params(), resource_context(workspace, db))

    rows = await _audit_rows(db, workspace)
    assert result["reason"] == "mcp_resource_not_available"
    assert manager.touched_remote is False
    assert len(rows) == 1
    assert rows[0].details["state"] == STATE_DISABLED
    assert rows[0].details["outcome"] == OUTCOME_DENIED
    assert OUTCOME_EXECUTED not in {row.details["outcome"] for row in rows}
