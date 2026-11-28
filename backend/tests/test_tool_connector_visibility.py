import pytest

from app.tools import discovery_impl
from app.tools.context import ToolContext
from app.tools.definitions import get_tool_definition_metadata
from app.tools.registry import execute_tool_with_plugins
from app.tools.visibility import connector_activation_decision, filter_tool_definitions_by_visibility


def _context(project_config: dict | None = None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["member"],
        session_id="session-1",
        project_config=project_config or {},
        db=None,
        workspace_root="/tmp/workspace",
        capability_type="diagnosis",
    )


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": f"{name} tool", "parameters": {"type": "object"}},
    }


def _names(definitions: list[dict]) -> list[str]:
    return [item["function"]["name"] for item in definitions]


def test_connector_activation_recognizes_explicit_and_legacy_project_config() -> None:
    assert connector_activation_decision("jira", {"jira_url": "https://jira.example.test"}) == (
        True,
        "project_connector_config_present",
        "jira_url",
    )
    assert connector_activation_decision("jira", {"connectors": {"jira": {"enabled": True}}}) == (
        True,
        "explicit_connector_activation",
        "connectors.jira",
    )
    assert connector_activation_decision(
        "jira",
        {"connectors": {"jira": {"enabled": False}}, "jira_url": "https://jira.example.test"},
    ) == (False, "explicit_connector_deactivation", "connectors.jira")


def test_generic_connector_metadata_preserves_provider_specific_ownership() -> None:
    assert get_tool_definition_metadata("aws_topology_snapshot").connector == "aws"
    assert get_tool_definition_metadata("invoke_aws_lambda").connector == "aws"
    assert get_tool_definition_metadata("list_azure_resource_groups").connector == "azure"
    assert get_tool_definition_metadata("list_gcp_projects").connector == "gcp"
    assert get_tool_definition_metadata("list_servicenow_incidents").connector == "servicenow"
    assert get_tool_definition_metadata("create_incident").connector == "incident_management"


def test_connector_visibility_filters_inactive_connector_tools_but_keeps_platform_tools() -> None:
    filtered = filter_tool_definitions_by_visibility(
        [_tool("knowledge_search"), _tool("search_jira_tickets"), _tool("get_confluence_page")],
        project_config={},
    )

    assert _names(filtered) == ["knowledge_search"]


def test_connector_visibility_allows_active_connector_tools() -> None:
    filtered = filter_tool_definitions_by_visibility(
        [_tool("knowledge_search"), _tool("search_jira_tickets"), _tool("get_confluence_page")],
        project_config={"connectors": {"jira": {"enabled": True}}},
    )

    assert _names(filtered) == ["knowledge_search", "search_jira_tickets"]






@pytest.mark.asyncio
async def test_lazy_tool_search_hides_inactive_connector_tools_and_exposes_active_tools() -> None:
    inactive = await discovery_impl.execute_tool_search({"query": "jira", "source": "connector"}, _context({}))
    assert "search_jira_tickets" not in {item["name"] for item in inactive["tools"]}

    active = await discovery_impl.execute_tool_search(
        {"query": "jira", "source": "connector"},
        _context({"jira_url": "https://jira.example.test"}),
    )
    assert "search_jira_tickets" in {item["name"] for item in active["tools"]}
    ticket = next(item for item in active["tools"] if item["name"] == "search_jira_tickets")
    assert ticket["visibility"]["reason"] == "project_connector_config_present"
    assert ticket["visibility"]["evidence"] == "jira_url"


@pytest.mark.asyncio
async def test_schema_get_denies_inactive_connector_tool_and_allows_active_connector_tool() -> None:
    blocked = await discovery_impl.execute_tool_schema_get({"tool_name": "search_jira_tickets"}, _context({}))
    assert blocked["policy"] == "connector_activation"
    assert blocked["visibility_decision"]["visible"] is False
    assert blocked["visibility_decision"]["connector"] == "jira"

    allowed = await discovery_impl.execute_tool_schema_get(
        {"tool_name": "search_jira_tickets"},
        _context({"connectors": {"jira": {"enabled": True}}}),
    )
    assert allowed["schema"]["function"]["name"] == "search_jira_tickets"
    assert allowed["metadata"]["connector"] == "jira"


@pytest.mark.asyncio
async def test_direct_execution_denies_inactive_connector_tool() -> None:
    result = await execute_tool_with_plugins("search_jira_tickets", {"query": "OCX"}, _context({}))

    assert result["policy"] == "connector_activation"
    assert result["tool_name"] == "search_jira_tickets"
    assert result["visibility_decision"]["reason"] == "connector_not_active_for_project"
