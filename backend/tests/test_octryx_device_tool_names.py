"""A device phase names the tools the device really has: a plan phase that shows ``list_workspace_directory``
makes the model call it as an MCP tool and get "No such tool available"."""

from app.services.workflow_runs.octryx.device_tools import device_tool_names, knowledge_mcp_tools
from app.services.workflow_runs.octryx.phase_view import _refresh_device_tools, _tools

PLAN_ALLOW = ["analyze_workspace_repository", "code_search", "grep_workspace", "glob_workspace_files",
              "list_workspace_directory", "read_workspace_file", "write_workspace_file", "edit_workspace_file",
              "multi_edit_workspace_file", "knowledge_search", "work_item_context", "submit_work_plan"]


def test_plan_phase_names_native_tools_and_only_offered_mcp_tools():
    names = device_tool_names(PLAN_ALLOW, ["bash"], mcp_tools=knowledge_mcp_tools())
    assert "LS/Glob (list_workspace_directory)" in names
    assert "Grep (code_search, grep_workspace)" in names
    assert "Read (read_workspace_file)" in names
    assert "mcp__octryx-knowledge__submit_work_plan" in names
    assert "mcp__octryx-knowledge__knowledge_search" in names
    assert not any("list_workspace_directory" in name and name.startswith("mcp__") for name in names)
    assert not any("analyze_workspace_repository" in name for name in names)  # no device counterpart


def test_denied_and_unknown_tools_are_left_out():
    assert device_tool_names(["read_workspace_file", "edit_workspace_file", "made_up"], ["edit_workspace_file"],
                             mcp_tools=frozenset()) == ["Read (read_workspace_file)"]


def test_policy_names_stay_for_the_gates_and_narrowing_refreshes_on_device():
    tools = _tools({"allowlist": ["read_workspace_file", "submit_work_plan"], "denylist": []})
    assert tools["allow"] == ["read_workspace_file", "submit_work_plan"]
    contract = {"phase": {"tools": {**tools, "allow": [], "deny": ["read_workspace_file", "submit_work_plan"]}}}
    _refresh_device_tools(contract)
    assert contract["phase"]["tools"]["on_device"] == []
