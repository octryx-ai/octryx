"""The run capability class of a remote MCP capability follows its classified risk.

The bridge tools are static reads, so before this a write capability of a foreign MCP server ran inside a
read_only run (every chat turn) and only the approval policy could hold it back. Now the risk an admin set on the
capability's Workspace binding decides: ``read`` → read_only, unclassified (``unknown``) → change,
``write``/``admin`` → deliver. Both dispatch paths refuse before the remote call.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.tools.capability_requirements import mcp_capability_required_class
from app.tools.registry import execute_tool_with_plugins
from tests.mcp_capability_support import (
    BRIDGE_TOOL,
    DIRECT_WRITE_TOOL,
    SERVER,
    WRITE_TOOL,
    RecordingMcpManager,
    create_mcp_workspace,
    enable_capability,
    install_mcp_manager,
    mcp_tool,
    mirror_tools,
)


def _in_run(context, run_class: str):
    return dataclasses.replace(context, run_capability={"class": run_class, "enforced": True})


def _bridge() -> dict:
    return {"server_name": SERVER, "tool_name": WRITE_TOOL, "arguments": {"path": "a"}}


def test_only_a_read_classified_capability_fits_a_read_only_run() -> None:
    assert mcp_capability_required_class("read") == "read_only"
    assert mcp_capability_required_class("unknown") == "change"
    assert mcp_capability_required_class("") == "change"
    assert mcp_capability_required_class("write") == "deliver"
    assert mcp_capability_required_class("admin") == "deliver"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("risk", "allowed_in"),
    [("read", {"read_only", "change", "deliver"}), ("write", {"deliver"}), ("admin", {"deliver"})],
)
async def test_classified_capability_runs_only_where_its_class_fits(db, monkeypatch, risk, allowed_in) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk=risk)

    for run_class in ("read_only", "change", "deliver"):
        context = _in_run(workspace.context(db), run_class)
        for tool, params in ((DIRECT_WRITE_TOOL, {"path": "a"}), (BRIDGE_TOOL, _bridge())):
            calls_before = len(manager.calls)
            result = await execute_tool_with_plugins(tool, params, context)
            if run_class in allowed_in:
                assert result.get("success") is True, (risk, run_class, tool, result)
                assert len(manager.calls) == calls_before + 1
            else:
                assert result["tool_execution"]["policy"] == "run_capability", (risk, run_class, tool)
                assert result["capability_refusal"]["required_capability"] == "deliver"
                assert result["capability_refusal"]["mcp_capability"]["risk"] == risk
                assert len(manager.calls) == calls_before


@pytest.mark.asyncio
async def test_unclassified_capability_is_refused_in_a_read_only_run_and_says_how_to_classify(db, monkeypatch) -> None:
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpManager([mcp_tool(WRITE_TOOL)]))
    await mirror_tools(db, workspace, [WRITE_TOOL])
    await enable_capability(db, workspace, WRITE_TOOL, risk="unknown")  # enabled, not yet classified

    refused = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, _in_run(workspace.context(db),
                                                                                        "read_only"))
    assert refused["capability_refusal"]["required_capability"] == "change"
    assert "classify this capability as 'read'" in refused["error"]
    assert manager.calls == []

    admitted = await execute_tool_with_plugins(DIRECT_WRITE_TOOL, {"path": "a"}, _in_run(workspace.context(db),
                                                                                         "change"))
    assert admitted.get("success") is True
    assert manager.calls == [(SERVER, WRITE_TOOL, {"path": "a"})]
