"""Tool definitions re-add enabled step tools after filtering, record loader failures and keep DB and read-only policies after the re-add."""

from __future__ import annotations

import json

import pytest

from app.agent.core.context.run_context_tooling import (
    DYNAMIC_DATABASE_CATALOG_METADATA_KEY,
    build_run_context_tool_definitions,
)
from app.tools.context import ToolContext
from app.tools.registry import execute_tool_with_plugins
from tests.run_context_tooling_support import _db_routing_resolution, _tool


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_readds_enabled_step_tools_after_filtering() -> None:
    captured_agent_type: dict[str, str] = {}

    async def fake_dynamic_loader(_db, _tool_context):
        return [_tool("dynamic_query")]

    tool_context = ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={"connectors": {"aws": {"enabled": True}}},
        db=None,
        workspace_root="/tmp/workspace",
    )
    tool_definitions = await build_run_context_tool_definitions(
        db=None,
        tool_context=tool_context,
        capability_type="diagnosis",
        include_tools=True,
        tool_allowlist=["read_workspace_file"],
        blocked_tools=["dynamic_query"],
        agent_definition={
            "steps": [
                {
                    "name": "Inspect",
                    "isEnabled": True,
                    "allowedTools": ["read_logs", "write_patch"],
                }
            ]
        },
        get_all_tools_with_plugins=lambda *, agent_type: (
            captured_agent_type.setdefault("value", agent_type) and [_tool("read_logs"), _tool("write_patch")]
        ),
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
        list_dynamic_database_tool_definitions=fake_dynamic_loader,
    )

    # The catalog follows the turn's capability; no keyword route switches it.
    assert captured_agent_type["value"] == "diagnosis"
    assert [definition["function"]["name"] for definition in tool_definitions] == [
        "read_logs",
        "write_patch",
    ]
    assert tool_context.tooling_metadata is not None
    assert tool_context.tooling_metadata[DYNAMIC_DATABASE_CATALOG_METADATA_KEY] == {
        "source": "database_tool_registry",
        "status": "loaded",
        "reason": "catalog_loaded",
        "tool_count": 1,
        "fail_closed": False,
    }


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_records_dynamic_database_loader_failure() -> None:
    async def failing_dynamic_loader(_db, _tool_context):
        raise RuntimeError("postgresql://admin:secret@example.invalid/app")

    tool_context = ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={"connectors": {"database": {"enabled": True}}},
        db=None,
        workspace_root="/tmp/workspace",
    )

    tool_definitions = await build_run_context_tool_definitions(
        db=None,
        tool_context=tool_context,
        capability_type="diagnosis",
        include_tools=True,
        tool_allowlist=[],
        blocked_tools=[],
        agent_definition=None,
        get_all_tools_with_plugins=lambda *, agent_type: [_tool("read_logs")],
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
        list_dynamic_database_tool_definitions=failing_dynamic_loader,
    )

    assert [definition["function"]["name"] for definition in tool_definitions] == ["read_logs"]
    assert tool_context.tooling_metadata is not None
    catalog_state = tool_context.tooling_metadata[DYNAMIC_DATABASE_CATALOG_METADATA_KEY]
    assert catalog_state == {
        "source": "database_tool_registry",
        "status": "unavailable",
        "reason": "catalog_load_failed",
        "tool_count": 0,
        "fail_closed": True,
        "error_type": "RuntimeError",
    }
    assert "secret" not in json.dumps(catalog_state).lower()


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_keeps_db_policy_after_step_tool_readd() -> None:
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
        tool_allowlist=["read_logs"],
        blocked_tools=[],
        agent_definition={
            "steps": [
                {
                    "name": "Inspect",
                    "isEnabled": True,
                    "allowedTools": ["read_logs", "write_patch", "aws_topology_snapshot"],
                }
            ]
        },
        get_all_tools_with_plugins=lambda *, agent_type: [
            _tool("read_logs"),
            _tool("write_patch"),
            _tool("aws_topology_snapshot"),
        ],
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
        workflow_routing_policy_resolution=_db_routing_resolution(allowlist=["aws_topology_snapshot"]),
    )

    assert [definition["function"]["name"] for definition in tool_definitions] == ["aws_topology_snapshot"]


@pytest.mark.asyncio
async def test_build_run_context_tool_definitions_enforces_project_read_only_policy_after_step_readd() -> None:
    tool_definitions = await build_run_context_tool_definitions(
        db=None,
        tool_context=ToolContext(
            user_id="user-1",
            project_ids=[],
            roles=["support"],
            session_id="session-1",
            project_config={"tool_policy": {"mode": "read_only"}},
            db=None,
            workspace_root="/tmp/workspace",
        ),
        capability_type="diagnosis",
        include_tools=True,
        tool_allowlist=["read_logs"],
        blocked_tools=[],
        agent_definition={
            "steps": [
                {
                    "name": "Inspect",
                    "isEnabled": True,
                        "allowedTools": ["read_workspace_file", "write_workspace_file", "bash"],
                }
            ]
        },
        get_all_tools_with_plugins=lambda *, agent_type: [
            _tool("read_workspace_file"),
            _tool("write_workspace_file"),
            _tool("bash"),
        ],
        filter_tool_definitions=lambda definitions, allowlist: [
            definition for definition in definitions if definition.get("function", {}).get("name") in set(allowlist)
        ],
        exclude_tool_definitions=lambda definitions, blocked: [
            definition for definition in definitions if definition.get("function", {}).get("name") not in set(blocked)
        ],
    )

    assert [definition["function"]["name"] for definition in tool_definitions] == ["read_workspace_file"]


@pytest.mark.asyncio
async def test_execute_tool_with_plugins_blocks_write_tool_for_project_read_only_policy() -> None:
    result = await execute_tool_with_plugins(
        "write_workspace_file",
        {"path": "notes.txt", "content": "hello"},
        ToolContext(
            user_id="user-1",
            project_ids=["support-project"],
            roles=["support"],
            session_id="session-1",
            project_config={"project_role": "support"},
            db=None,
            workspace_root="/tmp/workspace",
        ),
    )

    assert result["policy"] == "project_read_only_tools"
    assert "blocked" in result["error"].lower()
