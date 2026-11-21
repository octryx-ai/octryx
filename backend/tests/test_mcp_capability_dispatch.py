"""Dispatch and discovery decisions for mirrored MCP capabilities.

One decision function governs direct FQN dispatch, bridge dispatch, and
model-visible discovery. These tests pin that every denial happens *before* the
remote call, that both execution paths agree, that an unverifiable context denies
instead of guessing a workspace, and that discovery never answers an
unverifiable context with an empty-but-successful listing.
"""

from __future__ import annotations

import pytest

from app.services.mcp_capability_catalog import acknowledged_mcp_capability_schema_config
from app.tools.mcp_bridge import ListMcpServerToolsTool
from app.tools.registry import execute_tool_with_plugins
from tests.mcp_capability_support import (
    BRIDGE_TOOL,
    DIRECT_READ_TOOL,
    DIRECT_WRITE_TOOL,
    READ_TOOL,
    SERVER,
    WRITE_TOOL,
    RecordingMcpManager,
    capability_binding,
    create_mcp_workspace,
    enable_capability,
    install_mcp_manager,
    mcp_tool,
    mirror_tools,
    register_mcp_server,
)


def _bridge_params(tool_name: str = WRITE_TOOL, arguments: dict | None = None) -> dict:
    return {
        "server_name": SERVER,
        "tool_name": tool_name,
        "arguments": {"path": "a"} if arguments is None else arguments,
    }


@pytest.mark.asyncio
async def test_disabled_capability_denies_both_paths_before_remote_dispatch(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    context = workspace.context(db)

    direct = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    bridge = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params(), context)

    for result in (direct, bridge):
        assert result["blocked_by"] == "mcp_capability_policy"
        assert result["reason"] == "mcp_capability_disabled"
        assert result["tool_execution"]["category"] == "denied_by_policy"
        assert result["tool_execution"]["policy"] == "mcp_capability_policy"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_a_tool_without_a_binding_denies_even_when_others_are_enabled(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(READ_TOOL)]))
    await mirror_tools(db, workspace, [READ_TOOL])
    await enable_capability(db, workspace, READ_TOOL, risk="read")

    result = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, workspace.context(db))
    assert result["reason"] == "mcp_capability_not_bound"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_enabled_capability_admits_both_paths_with_decision_parity(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="read")
    context = workspace.context(db)

    direct = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    bridge = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params(), context)

    assert direct.get("success") is True
    assert bridge.get("success") is True
    assert manager.calls == [(SERVER, WRITE_TOOL, {"path": "a"}), (SERVER, WRITE_TOOL, {"path": "a"})]


@pytest.mark.asyncio
async def test_a_newly_registered_servers_tool_is_denied_until_its_binding_is_enabled(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await register_mcp_server(db, workspace)
    context = workspace.context(db)

    for result in (await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context),
                   await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params(), context)):
        assert result["blocked_by"] == "mcp_capability_policy"
        assert result["reason"] == "mcp_capability_not_bound"
        assert result["capability_decision"]["capability_state"] == "unbound"
    assert manager.calls == []

    await mirror_tools(db, workspace, [WRITE_TOOL])  # the mirror binds it disabled
    assert (await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context))["reason"] == (
        "mcp_capability_disabled")
    await enable_capability(db, workspace, WRITE_TOOL, risk="read")  # the admin enables it
    assert (await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)).get("success") is True
    assert manager.calls == [(SERVER, WRITE_TOOL, {"path": "a"})]


@pytest.mark.asyncio
async def test_an_enabled_capability_still_goes_through_the_approval_policy(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="write")

    guarded = workspace.context(db, approval_policy={"require_for_risks": ["write"]})
    blocked = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "b"}, guarded)
    assert blocked["approval_required"] is True
    assert blocked["approval_subject"] == DIRECT_WRITE_TOOL
    assert manager.calls == []


@pytest.mark.asyncio
async def test_a_server_name_case_variant_resolves_the_same_binding(db, monkeypatch) -> None:
    """``mcp__Demo__write_doc`` is the mirrored server, so its disabled binding decides."""
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    context = workspace.context(db)

    direct = await execute_tool_with_plugins(f"mcp__Demo__{WRITE_TOOL}", {"path": "a"}, context)
    bridge = await execute_tool_with_plugins(
        BRIDGE_TOOL,
        {"server_name": "DEMO", "tool_name": WRITE_TOOL, "arguments": {"path": "a"}},
        context,
    )

    for result in (direct, bridge):
        assert result["blocked_by"] == "mcp_capability_policy"
        assert result["reason"] == "mcp_capability_disabled"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_missing_workspace_context_denies_before_remote_dispatch(db, monkeypatch) -> None:
    """No project id anywhere in the context is unverifiable and denies."""
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    context = workspace.unverifiable_context(db, project_ids=[])

    result = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    assert result["reason"] == "missing_workspace_context"
    assert result["blocked_by"] == "mcp_capability_policy"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_ambiguous_workspace_context_denies_before_remote_dispatch(db, monkeypatch) -> None:
    """Several competing project ids stay unverifiable; the server never decides for the caller."""
    workspace = await create_mcp_workspace(db)
    other = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    context = workspace.unverifiable_context(db, project_ids=[workspace.project.id, other.project.id])

    result = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    assert result["reason"] == "ambiguous_workspace_context"
    assert result["blocked_by"] == "mcp_capability_policy"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_flow_built_context_resolves_its_single_project_on_both_paths(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="read")
    context = workspace.flow_context(db)

    direct = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    bridge = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params(), context)

    assert direct.get("success") is True
    assert bridge.get("success") is True
    assert manager.calls == [(SERVER, WRITE_TOOL, {"path": "a"}), (SERVER, WRITE_TOOL, {"path": "a"})]


@pytest.mark.asyncio
async def test_flow_built_context_is_still_governed_by_the_binding(db, monkeypatch) -> None:
    """Resolving the workspace from the context grants no extra reach."""
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    context = workspace.flow_context(db)

    direct = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    bridge = await execute_tool_with_plugins(BRIDGE_TOOL, _bridge_params(), context)

    for result in (direct, bridge):
        assert result["blocked_by"] == "mcp_capability_policy"
        assert result["reason"] == "mcp_capability_disabled"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_a_server_that_mirrored_no_tools_denies_its_tools(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager())

    result = await mirror_tools(db, workspace, [])
    assert result["mirrored"] == 0

    denied = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, workspace.context(db))
    assert denied["blocked_by"] == "mcp_capability_policy"
    assert denied["reason"] == "mcp_capability_not_bound"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_deleting_a_tools_binding_denies_the_tool(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await db.delete(await capability_binding(db, workspace, WRITE_TOOL))
    await db.flush()

    denied = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, workspace.context(db))
    assert denied["reason"] == "mcp_capability_not_bound"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_inactive_capability_type_denies_before_remote_dispatch(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    binding = await enable_capability(db, workspace, WRITE_TOOL, risk="read")
    binding.capability_type.is_active = False
    await db.flush()

    denied = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, workspace.context(db))
    assert denied["reason"] == "mcp_capability_type_inactive"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_schema_drift_denies_until_an_admin_re_enables_the_capability(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="read")
    await mirror_tools(
        db,
        workspace,
        [mcp_tool(WRITE_TOOL, properties={"path": {"type": "string"}, "force": {"type": "boolean"}})],
    )
    context = workspace.context(db)

    denied = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    assert denied["blocked_by"] == "mcp_capability_policy"
    assert denied["reason"] == "mcp_capability_schema_drift"
    assert denied["capability_decision"]["capability_state"] == "needs_review"
    assert manager.calls == []

    # Re-enabling is the explicit review decision for the new contract.
    binding = await capability_binding(db, workspace, WRITE_TOOL)
    acknowledged = acknowledged_mcp_capability_schema_config(binding.binding_config)
    assert acknowledged is not None
    binding.binding_config = acknowledged
    binding.is_enabled = True
    await db.flush()

    allowed = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, context)
    assert allowed.get("success") is True
    assert manager.calls == [(SERVER, WRITE_TOOL, {"path": "a"})]
    binding = await capability_binding(db, workspace, WRITE_TOOL)
    assert "reviewState" not in binding.binding_config
    assert binding.binding_config["acknowledgedSchemaDigest"] == binding.binding_config["schemaDigest"]


@pytest.mark.asyncio
async def test_discovery_matches_dispatch_visibility_and_reports_risk(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    tools = [mcp_tool(READ_TOOL), mcp_tool(WRITE_TOOL)]
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager(tools))
    await mirror_tools(db, workspace, tools)
    await enable_capability(db, workspace, WRITE_TOOL, risk="write")
    context = workspace.context(db, approval_policy={"require_for_risks": ["write"]})

    listing = await ListMcpServerToolsTool().execute({"server_name": SERVER}, context)
    assert listing["count"] == 1
    assert listing["tools"][0]["name"] == WRITE_TOOL
    assert listing["tools"][0]["risk"] == "write"
    assert listing["tools"][0]["approval_required"] is True
    # An empty or filtered listing is never ambiguous: governance reports itself.
    assert listing["capability_governance"] == {"state": "enforced", "discovered": 2, "visible": 1}

    # The capability the model cannot see is also the one it cannot dispatch.
    denied = await execute_tool_with_plugins(DIRECT_READ_TOOL, {"path": "a"}, context)
    assert denied["blocked_by"] == "mcp_capability_policy"
    assert manager.calls == []


@pytest.mark.asyncio
async def test_discovery_on_an_unverifiable_context_is_an_explicit_denial(db, monkeypatch) -> None:
    """No workspace means no decision — discovery must not report a successful empty catalog."""
    workspace = await create_mcp_workspace(db)
    tools = [mcp_tool(READ_TOOL), mcp_tool(WRITE_TOOL)]
    install_mcp_manager(monkeypatch, RecordingMcpManager(tools))
    await mirror_tools(db, workspace, tools)
    await enable_capability(db, workspace, WRITE_TOOL, risk="write")
    context = workspace.unverifiable_context(db, project_ids=[])

    listing = await ListMcpServerToolsTool().execute({"server_name": SERVER}, context)
    assert listing["blocked_by"] == "mcp_capability_policy"
    assert listing["reason"] == "missing_workspace_context"
    assert listing["capability_decision"]["capability_state"] == "unverifiable"
    assert "tools" not in listing
    assert "count" not in listing
