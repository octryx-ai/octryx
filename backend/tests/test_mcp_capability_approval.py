"""Approval identity for mirrored MCP capabilities.

A capability dispatch has two policy identities — the tool the model called and
the ``mcp__<server>__<tool>`` capability subject — and each is waived only by an
exemption naming it. These tests pin both directions of that rule plus the
argument-bound grant that every path shares.
"""

from __future__ import annotations

import pytest

from app.services.approval.resolution_service import resolve_approval_request
from app.tools.registry import execute_tool_with_plugins
from tests.mcp_capability_support import (
    BRIDGE_TOOL,
    DIRECT_READ_TOOL,
    DIRECT_WRITE_TOOL,
    READ_TOOL,
    SERVER,
    WRITE_TOOL,
    RecordingMcpManager,
    create_mcp_workspace,
    enable_capability,
    install_mcp_manager,
    mcp_tool,
    mirror_tools,
)


def _bridge_params(arguments: dict) -> dict:
    return {"server_name": SERVER, "tool_name": WRITE_TOOL, "arguments": arguments}


@pytest.mark.asyncio
async def test_approval_policy_risk_floor_survives_the_capability_subject(db, monkeypatch) -> None:
    """A mirrored read capability must not escape a pre-existing read-risk rule."""
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(READ_TOOL)]))
    await mirror_tools(db, workspace, [READ_TOOL])
    # Explicitly governed as the lowest risk the catalog can express.
    await enable_capability(db, workspace, READ_TOOL, risk="unknown")
    context = workspace.context(db, approval_policy={"require_for_risks": ["read"]})

    result = await execute_tool_with_plugins(DIRECT_READ_TOOL, {"path": "a"}, context)
    assert result["approval_required"] is True
    assert manager.calls == []


@pytest.mark.asyncio
async def test_write_capability_binds_one_argument_scoped_approval_across_both_paths(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="write")
    context = workspace.context(db, approval_policy={"require_for_risks": ["write"]})
    arguments = {"path": "a"}

    direct = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, arguments, context)
    assert direct["approval_required"] is True
    assert direct["approval_subject"] == DIRECT_WRITE_TOOL
    assert manager.calls == []

    # The bridge addresses the same capability with the same arguments, so it
    # joins the pending approval instead of creating a second one.
    bridge = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params(arguments), context)
    assert bridge["approval_id"] == direct["approval_id"]
    assert manager.calls == []

    await resolve_approval_request(
        db,
        approval_id=direct["approval_id"],
        resolved_by=workspace.user.id,
        status="approved",
    )

    # A different argument set is not covered by the grant.
    other = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "b"}, context)
    assert other["approval_required"] is True
    assert other["approval_id"] != direct["approval_id"]
    assert manager.calls == []

    granted = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params(arguments), context)
    assert granted.get("success") is True
    assert manager.calls == [(SERVER, WRITE_TOOL, arguments)]


@pytest.mark.asyncio
async def test_subject_exemption_cannot_waive_an_existing_bridge_approval_rule(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="read")
    context = workspace.context(
        db,
        approval_policy={"require_for_tools": [BRIDGE_TOOL], "exempt_tools": [DIRECT_WRITE_TOOL]},
    )

    bridge = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params({"path": "a"}), context)
    assert bridge["approval_required"] is True
    assert manager.calls == []

    # The exemption still governs the tool it actually names.
    direct = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    assert direct.get("success") is True
    assert manager.calls == [(SERVER, WRITE_TOOL, {"path": "a"})]


@pytest.mark.asyncio
async def test_dispatched_tool_exemption_cannot_waive_a_capability_tool_rule(db, monkeypatch) -> None:
    """The mirror of the rule above: exempting the bridge does not free the capability."""
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="read")
    context = workspace.context(
        db,
        approval_policy={"require_for_tools": [DIRECT_WRITE_TOOL], "exempt_tools": [BRIDGE_TOOL]},
    )

    bridge = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params({"path": "a"}), context)
    direct = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)

    # Same capability, same arguments, same decision on both paths.
    for result in (bridge, direct):
        assert result["approval_required"] is True
        assert result["approval_subject"] == DIRECT_WRITE_TOOL
    assert bridge["approval_id"] == direct["approval_id"]
    assert manager.calls == []


@pytest.mark.asyncio
async def test_dispatched_tool_exemption_cannot_waive_a_capability_risk_rule(db, monkeypatch) -> None:
    """A write-risk capability stays approval-bound even when the bridge is exempt."""
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="write")
    context = workspace.context(
        db,
        approval_policy={"require_for_risks": ["write"], "exempt_tools": [BRIDGE_TOOL]},
    )

    bridge = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params({"path": "a"}), context)
    assert bridge["approval_required"] is True
    assert bridge["approval_subject"] == DIRECT_WRITE_TOOL
    assert manager.calls == []
