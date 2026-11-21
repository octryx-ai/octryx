"""Workflow routing tool policies (DB, pattern, read-only, autonomous source reads, unmatched) applied to run context tool definitions."""

from __future__ import annotations

import pytest

from app.agent.core.context.run_context_tooling import build_run_context_tool_definitions
from app.tools.context import ToolContext
from tests.run_context_tooling_support import _db_routing_resolution, _tool


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_applies_db_routing_tool_policy() -> None:
    tool_definitions = await build_run_context_tool_definitions(
        db=None,
        tool_context=ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["admin"],
            session_id="session-1",
            project_config={"connectors": {"aws": {"enabled": True}}},
            db=None,
            workspace_root="/tmp/workspace",
        ),
        capability_type="diagnosis",
        include_tools=True,
        tool_allowlist=[],
        blocked_tools=[],
        agent_definition=None,
        get_all_tools_with_plugins=lambda *, agent_type: [
            _tool("aws_topology_snapshot"),
            _tool("get_shape_library"),
            _tool("create_diagram"),
            _tool("bash"),
        ],
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
        workflow_routing_policy_resolution=_db_routing_resolution(
            allowlist=["aws_topology_snapshot", "get_shape_library", "create_diagram"],
            denylist=["create_diagram"],
        ),
    )

    assert [definition["function"]["name"] for definition in tool_definitions] == [
        "aws_topology_snapshot",
        "get_shape_library",
    ]


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_applies_pattern_routing_tool_policy() -> None:
    tool_definitions = await build_run_context_tool_definitions(
        db=None,
        tool_context=ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["admin"],
            session_id="session-1",
            project_config={},
            db=None,
            workspace_root="/tmp/workspace",
        ),
        capability_type="diagnosis",
        include_tools=True,
        tool_allowlist=[],
        blocked_tools=[],
        agent_definition=None,
        get_all_tools_with_plugins=lambda *, agent_type: [
            _tool("list_workspace_directory"),
            _tool("list_workspace_git_commits"),
            _tool("knowledge_search"),
            _tool("write_workspace_file"),
            _tool("instruction_get"),
        ],
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
        workflow_routing_policy_resolution=_db_routing_resolution(
            allow_patterns=["list_*"],
            deny_patterns=["*_commits"],
        ),
    )

    assert [definition["function"]["name"] for definition in tool_definitions] == [
        "list_workspace_directory",
        "instruction_get",
    ]


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_applies_read_only_routing_tool_policy() -> None:
    tool_definitions = await build_run_context_tool_definitions(
        db=None,
        tool_context=ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["admin"],
            session_id="session-1",
            project_config={},
            db=None,
            workspace_root="/tmp/workspace",
        ),
        capability_type="diagnosis",
        include_tools=True,
        tool_allowlist=[],
        blocked_tools=[],
        agent_definition=None,
        get_all_tools_with_plugins=lambda *, agent_type: [
            _tool("knowledge_search"),
            _tool("knowledge_read"),
            _tool("write_workspace_file"),
            _tool("instruction_get"),
        ],
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
        workflow_routing_policy_resolution=_db_routing_resolution(allow_read_only=True),
    )

    assert [definition["function"]["name"] for definition in tool_definitions] == [
        "knowledge_search",
        "knowledge_read",
        "instruction_get",
    ]


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_exposes_source_read_tools_for_autonomous_mode() -> None:
    tool_definitions = await build_run_context_tool_definitions(
        db=None,
        tool_context=ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["admin"],
            session_id="session-1",
            project_config={"connectors": {"jira": {"enabled": True}}},
            db=None,
            workspace_root="/tmp/workspace",
        ),
        capability_type="diagnosis",
        include_tools=True,
        tool_allowlist=["knowledge_search"],
        blocked_tools=[],
        agent_definition=None,
        get_all_tools_with_plugins=lambda *, agent_type: [
            _tool("knowledge_search"),
            _tool("list_jira_versions"),
            _tool("search_jira_tickets"),
            _tool("write_workspace_file"),
            _tool("instruction_get"),
        ],
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
        workflow_routing_policy_resolution=_db_routing_resolution(
            allowlist=["list_jira_versions", "search_jira_tickets", "knowledge_search"],
            workflow_contract={
                "workflow_id": "source_evidence_lookup",
                "source_steps": [
                    {"tool": "list_jira_versions", "params": {}},
                    {"tool": "search_jira_tickets", "params": {"query": "{topic}"}},
                ],
            },
        ),
    )

    assert [definition["function"]["name"] for definition in tool_definitions] == [
        "knowledge_search",
        "list_jira_versions",
        "search_jira_tickets",
        "instruction_get",
    ]


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_ignores_unmatched_routing_policy() -> None:
    tool_definitions = await build_run_context_tool_definitions(
        db=None,
        tool_context=ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["admin"],
            session_id="session-1",
            project_config={},
            db=None,
            workspace_root="/tmp/workspace",
        ),
        capability_type="diagnosis",
        include_tools=True,
        tool_allowlist=[],
        blocked_tools=[],
        agent_definition=None,
        get_all_tools_with_plugins=lambda *, agent_type: [_tool("read_logs"), _tool("write_patch")],
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
        workflow_routing_policy_resolution={
            "source": "code",
            "status": "fallback",
            "tool_policy": {"allowlist": ["aws_topology_snapshot"], "denylist": []},
        },
    )

    assert [definition["function"]["name"] for definition in tool_definitions] == ["read_logs", "write_patch"]
