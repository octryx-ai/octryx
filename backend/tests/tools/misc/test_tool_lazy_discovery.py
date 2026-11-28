"""Tests for lazy tool discovery runtime."""

import pytest

from app.tools import discovery_impl
from app.tools.definitions import (
    get_all_definitions,
    get_core_tool_names,
    get_discoverable_tool_names,
    get_tool_definition_metadata,
    is_tool_definition_available_for_agent_type,
)


class TestCoreVsDiscoverable:
    def test_tool_search_and_tool_schema_get_are_core(self):
        assert get_tool_definition_metadata("tool_search").is_core is True
        assert get_tool_definition_metadata("tool_schema_get").is_core is True

    def test_core_tools_includes_expected_tools(self):
        core = get_core_tool_names("diagnosis")
        assert "tool_search" in core
        assert "tool_schema_get" in core
        assert "bash" in core
        assert "skill_search" in core
        assert "knowledge_search" in core
        assert "list_mcp_servers" in core

    def test_discoverable_tools_excludes_core(self):
        discoverable = get_discoverable_tool_names("diagnosis")
        assert "tool_search" not in discoverable
        assert "tool_schema_get" not in discoverable
        assert "bash" not in discoverable

    def test_discoverable_tools_includes_long_tail(self):
        discoverable = get_discoverable_tool_names("diagnosis")
        assert "lsp_hover" in discoverable
        assert "admin_list_users" in discoverable

    def test_core_plus_discoverable_covers_all_agent_available_tools(self):
        agent_type = "diagnosis"
        core = set(get_core_tool_names(agent_type))
        discoverable = set(get_discoverable_tool_names(agent_type))
        available = {name for name in get_all_definitions() if is_tool_definition_available_for_agent_type(name, agent_type)}
        assert core | discoverable == available
        assert core & discoverable == set()

    def test_tool_search_is_available_for_all_agent_types(self):
        for agent_type in ("diagnosis", "change", "plan", "admin"):
            assert is_tool_definition_available_for_agent_type("tool_search", agent_type)
            assert is_tool_definition_available_for_agent_type("tool_schema_get", agent_type)

    def test_aws_action_operation_is_not_available_for_diagnosis_agent(self):
        assert not is_tool_definition_available_for_agent_type("aws_action_operation", "diagnosis")
        assert is_tool_definition_available_for_agent_type("aws_action_operation", "change")

    def test_plan_excluded_tools_not_in_core_for_plan_agent(self):
        core_plan = get_core_tool_names("plan")
        assert "bash" not in core_plan

    def test_connector_tool_metadata_is_explicit(self):
        read_metadata = get_tool_definition_metadata("search_jira_tickets")
        assert read_metadata.owner_type == "connector"
        assert read_metadata.source == "connector"
        assert read_metadata.connector == "jira"
        assert read_metadata.required_config == "connector:jira"
        assert read_metadata.risk == "read"
        assert read_metadata.approval_required is False
        assert read_metadata.scopes == ("connector:jira",)
        assert read_metadata.mutates_state is False
        assert read_metadata.filesystem_access == "none"
        assert read_metadata.network_access == "connector"
        assert read_metadata.audit_required is True

        write_metadata = get_tool_definition_metadata("create_confluence_page")
        assert write_metadata.owner_type == "connector"
        assert write_metadata.source == "connector"
        assert write_metadata.connector == "confluence"
        assert write_metadata.required_config == "connector:confluence"
        assert write_metadata.risk == "write"
        assert write_metadata.approval_required is True
        assert write_metadata.scopes == ("connector:confluence",)
        assert write_metadata.mutates_state is True
        assert write_metadata.network_access == "connector"
        assert write_metadata.audit_required is True

    def test_dynamic_database_tool_metadata_defaults_to_safe_database_owner(self):
        metadata = get_tool_definition_metadata("database_tool_customer_lookup")
        assert metadata.owner_type == "dynamic_database"
        assert metadata.source == "database"
        assert metadata.required_config == "database_tool_registry"
        assert metadata.risk == "read"
        assert metadata.approval_required is False
        assert metadata.scopes == ("database:query_tool",)
        assert metadata.mutates_state is False
        assert metadata.network_access == "database"
        assert metadata.audit_required is True

    def test_admin_tool_metadata_requires_admin_risk(self):
        metadata = get_tool_definition_metadata("admin_list_users")
        assert metadata.owner_type == "built_in"
        assert metadata.source == "base"
        assert metadata.risk == "admin"
        assert metadata.approval_required is True
        assert metadata.mutates_state is True
        assert metadata.audit_required is True

    def test_unknown_tool_metadata_requires_configuration(self):
        metadata = get_tool_definition_metadata("safe_custom_tool")
        assert metadata.owner_type == "unknown"
        assert metadata.source == "unknown"
        assert metadata.required_config == "tool_definition_metadata"
        assert metadata.risk == "unknown"
        assert metadata.approval_required is True
        assert metadata.network_access == "unknown"
        assert metadata.audit_required is True

    def test_workspace_tool_metadata_records_filesystem_need(self):
        read_metadata = get_tool_definition_metadata("read_workspace_file")
        assert read_metadata.filesystem_access == "read"
        assert read_metadata.mutates_state is False

        write_metadata = get_tool_definition_metadata("write_workspace_file")
        assert write_metadata.filesystem_access == "write"
        assert write_metadata.mutates_state is True


class TestToolDefinitions:
    def test_tool_search_definition_has_required_fields(self):
        defs = get_all_definitions()
        ts_def = defs["tool_search"]
        func = ts_def["function"]
        assert func["name"] == "tool_search"
        assert "query" in func["parameters"]["properties"]
        assert "limit" in func["parameters"]["properties"]

    def test_tool_schema_get_definition_has_required_fields(self):
        defs = get_all_definitions()
        tsg_def = defs["tool_schema_get"]
        func = tsg_def["function"]
        assert func["name"] == "tool_schema_get"
        assert "tool_name" in func["parameters"]["properties"]

    def test_discoverable_tool_definitions_have_no_schema_in_search_results(self):
        discoverable = get_discoverable_tool_names("diagnosis")
        defs = get_all_definitions()
        for name in discoverable[:5]:
            assert name in defs
            assert "function" in defs[name]


@pytest.mark.asyncio
async def test_tool_search_uses_governance_metadata_not_description_keywords(monkeypatch):
    monkeypatch.setattr(
        discovery_impl,
        "get_all_definitions",
        lambda: {
            "safe_custom_tool": {
                "type": "function",
                "function": {
                    "name": "safe_custom_tool",
                    "description": "Read-only helper whose description says delete, write, patch, commit, and admin.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        },
    )

    write_result = await discovery_impl.execute_tool_search(
        {"query": "delete", "risk": "write"},
        context=None,
    )
    assert write_result["tools"] == []

    read_result = await discovery_impl.execute_tool_search(
        {"query": "delete", "risk": "read"},
        context=None,
    )
    assert read_result["tools"] == []

    unknown_result = await discovery_impl.execute_tool_search(
        {"query": "delete", "risk": "unknown"},
        context=None,
    )
    assert unknown_result["tools"][0]["name"] == "safe_custom_tool"
    assert unknown_result["tools"][0]["risk"] == "unknown"
    assert unknown_result["tools"][0]["source"] == "unknown"
    assert unknown_result["tools"][0]["required_config"] == "tool_definition_metadata"
    assert unknown_result["tools"][0]["approval_required"] is True
    assert unknown_result["tools"][0]["network_access"] == "unknown"
    assert unknown_result["tools"][0]["audit_required"] is True

    schema_result = await discovery_impl.execute_tool_schema_get(
        {"tool_name": "safe_custom_tool"},
        context=None,
    )
    assert schema_result["error"] == "Tool 'safe_custom_tool' requires explicit governance metadata before schema exposure"
