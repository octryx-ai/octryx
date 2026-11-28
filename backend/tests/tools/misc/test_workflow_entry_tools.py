"""Tests for governed workflow entry: list_available_workflows + start_workflow."""

from __future__ import annotations

import pytest

from app.tools.context import ToolContext
from app.tools.definitions import (
    get_all_definitions,
    get_tool_definition_metadata,
    is_tool_definition_available_for_agent_type,
)
from app.tools.workflow_tools import ListAvailableWorkflowsTool, StartWorkflowTool

_JIRA_PROJECT_CONFIG = {"connectors": {"jira": {"enabled": True}}}


def _tool_context(
    *,
    project_config: dict | None = None,
    current_user_message: str = "What is the status of release 25.10?",
    turn_context_snapshot: dict | None = None,
    db=None,
) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["developer"],
        session_id="session-1",
        project_config=dict(project_config or {}),
        current_user_message=current_user_message,
        turn_context_snapshot=turn_context_snapshot,
        db=db,
    )


@pytest.mark.asyncio
async def test_list_available_workflows_lists_no_registry_workflow() -> None:
    # The catalog is the published phased workflows; a context without a database lists nothing.
    result = await ListAvailableWorkflowsTool().execute({}, _tool_context(project_config=_JIRA_PROJECT_CONFIG))
    assert result == {"workflows": [], "count": 0}


@pytest.mark.asyncio
async def test_start_workflow_proposes_a_phased_workflow_and_never_starts_it(db) -> None:
    proposed = await StartWorkflowTool().execute(
        {"workflow_id": "incident-analysis", "reason": "production incident"}, _tool_context(db=db))
    assert (proposed["status"], proposed["reason"]) == ("needs_confirmation", "workflow_run_required")
    assert proposed["workflow_key"] == "incident-analysis"
    assert proposed["proposal_reason"] == "production incident"

    for workflow_id in ("jira_release_status", "unknown_workflow"):
        result = await StartWorkflowTool().execute(
            {"workflow_id": workflow_id, "reason": "release status question"}, _tool_context(db=db))
        assert (result["status"], result["reason"]) == ("needs_clarification", "unknown_key")
        assert workflow_id in result["error"]


@pytest.mark.asyncio
async def test_start_workflow_requires_workflow_id_and_reason() -> None:
    tool = StartWorkflowTool()
    context = _tool_context(project_config=_JIRA_PROJECT_CONFIG)

    assert "workflow_id is required" in (await tool.execute({}, context))["error"]
    assert "reason is required" in (await tool.execute({"workflow_id": "jira_release_status"}, context))["error"]


def test_workflow_entry_tools_governance_metadata_pins() -> None:
    for tool_name in ("start_workflow", "list_available_workflows"):
        metadata = get_tool_definition_metadata(tool_name)
        assert metadata.owner_type == "built_in"
        assert metadata.source == "base"
        assert metadata.risk == "read"
        assert metadata.approval_required is False
        assert metadata.mutates_state is False
        assert metadata.change_only is False

    definitions = get_all_definitions()
    assert "start_workflow" in definitions
    assert "list_available_workflows" in definitions
    start_description = definitions["start_workflow"]["function"]["description"]
    assert "list_available_workflows" in start_description
    assert set(definitions["start_workflow"]["function"]["parameters"]["required"]) == {"workflow_id", "reason"}


def test_workflow_entry_tools_agent_type_visibility() -> None:
    for agent_type in ("diagnosis", "change", "operations"):
        assert is_tool_definition_available_for_agent_type("start_workflow", agent_type) is True
        assert is_tool_definition_available_for_agent_type("list_available_workflows", agent_type) is True
    # The plan agent only keeps the read-only listing.
    assert is_tool_definition_available_for_agent_type("start_workflow", "plan") is False
    assert is_tool_definition_available_for_agent_type("list_available_workflows", "plan") is True
