"""Contract: tools implemented under ``tools/connectors/`` are connector-owned."""

from __future__ import annotations

import pytest

from app.services.tool_access_policy import tool_project_policy_decision
from app.services.tool_config import TOOL_CONFIG_PRESETS
from app.tools.capability_requirements import CAPABILITY_DELIVER, tool_required_capability
from app.tools.connector_activation_catalog import COMPOSITE_CONNECTOR_MEMBERS, CONNECTOR_CONFIG_KEYS
from app.tools.definitions import get_tool_definition_metadata
from app.tools.definitions.connector_ownership import (
    CONNECTOR_BY_OWNED_TOOL,
    CONNECTOR_TOOL_OWNERSHIP,
    SERVICE_ONLY_TOOL_CONNECTORS,
    SERVICE_ONLY_TOOLS,
)
from app.tools.registry import TOOL_REGISTRY_ENTRIES, execute_tool, get_tool_definitions
from app.tools.visibility import connector_activation_decision, tool_visibility_decision

# External writes that belong to their connectors, never to the built-in tools.
_CONNECTOR_OWNED_WRITES = {
    "trigger_workflow": "ci_pipelines",
    "cancel_pipeline": "ci_pipelines",
    "retry_job": "ci_pipelines",
    "apply": "terraform",
    "upgrade": "helm",
    "rollback": "helm",
    "sync_app": "argocd",
    "rollback_app": "argocd",
    "run_playbook": "ansible",
    "delete_tag": "docker_registry",
    "renew_lease": "vault",
    "revoke_token": "vault",
    "create_issue": "linear",
    "update_issue": "linear",
    "create_meeting": "outlook",
    "send_meeting_invite": "outlook",
    "update_component_status": "statuspage",
    "create_snapshot": "grafana",
}

# Tool-config preset (admin connector) -> the connector that owns its tools.
_PRESET_CONNECTOR = {
    "ansible": "ansible",
    "argocd": "argocd",
    "azure_devops": "azure_devops",
    "datadog": "datadog",
    "docker_registry": "docker_registry",
    "elasticsearch": "elasticsearch",
    "grafana": "grafana",
    "helm": "helm",
    "ldap": "ldap",
    "linear": "linear",
    "newrelic": "newrelic",
    "notion": "notion",
    "outlook_calendar": "outlook",
    "sharepoint": "sharepoint",
    "snyk": "snyk",
    "sonarqube": "sonarqube",
    "splunk": "splunk",
    "statuspage": "statuspage",
    "terraform": "terraform",
    "vault": "vault",
}


def test_no_tool_implemented_under_connectors_is_registered_as_built_in():
    not_connector_owned = sorted(
        entry.name
        for entry in TOOL_REGISTRY_ENTRIES.values()
        if entry.implementation_module.startswith("app.tools.connectors.") and entry.owner_type != "connector"
    )
    assert not_connector_owned == []


def test_ownership_table_does_not_shadow_a_definition_module_owner():
    # ``CONNECTOR_PROVIDER_BY_TOOL`` merges the table last; a silent override of an
    # owner derived from a definition module would be a hidden ownership change.
    from app.tools import definitions
    from app.tools.definitions.bitbucket import get_bitbucket_definitions
    from app.tools.definitions.classification import GENERIC_CONNECTOR_DEFINITIONS, INCIDENT_MANAGEMENT_DEFINITION_NAMES
    from app.tools.definitions.confluence import get_confluence_definitions
    from app.tools.definitions.github import get_github_definitions
    from app.tools.definitions.gitlab import get_gitlab_definitions
    from app.tools.definitions.jira import get_jira_definitions

    module_owned = {
        *get_bitbucket_definitions(),
        *get_confluence_definitions(),
        *get_github_definitions(),
        *get_gitlab_definitions(),
        *get_jira_definitions(),
        *GENERIC_CONNECTOR_DEFINITIONS,
        *INCIDENT_MANAGEMENT_DEFINITION_NAMES,
    }
    assert sorted(module_owned & set(CONNECTOR_BY_OWNED_TOOL)) == []
    all_definitions = definitions.get_all_definitions()
    assert sorted(name for name in CONNECTOR_BY_OWNED_TOOL if name not in all_definitions) == []


@pytest.mark.parametrize(("tool_name", "connector"), sorted(_CONNECTOR_OWNED_WRITES.items()))
def test_former_built_in_external_writes_are_connector_owned_high_risk_writes(tool_name, connector):
    metadata = get_tool_definition_metadata(tool_name)
    assert (metadata.owner_type, metadata.connector) == ("connector", connector)
    assert metadata.required_config == f"connector:{connector}"
    assert (metadata.risk, metadata.approval_required, metadata.mutates_state) == ("write", True, True)
    assert tool_project_policy_decision(tool_name, {}).requires_explicit_allow is True
    assert tool_required_capability(tool_name) == CAPABILITY_DELIVER


def test_every_owning_connector_has_an_activation_path():
    without_activation = sorted(
        connector
        for connector in CONNECTOR_TOOL_OWNERSHIP
        if not CONNECTOR_CONFIG_KEYS.get(connector) and not COMPOSITE_CONNECTOR_MEMBERS.get(connector)
    )
    assert without_activation == sorted(SERVICE_ONLY_TOOL_CONNECTORS)


def test_service_only_owners_are_the_service_only_named_connections():
    from app.services.named_connections.descriptors import SERVICE_ONLY_CONNECTORS

    assert SERVICE_ONLY_TOOL_CONNECTORS <= SERVICE_ONLY_CONNECTORS
    assert SERVICE_ONLY_TOOLS == {"list_jenkins_builds"}


@pytest.mark.asyncio
async def test_a_service_only_tool_is_not_offered_to_chat_even_with_its_connector_activated():
    from app.services.work_role_model.tool_catalog import catalog_tool_names
    from app.tools.context import ToolContext
    from app.tools.discovery_impl import execute_tool_search

    config = {"enabled_connectors": ["jenkins"], "jenkins_url": "https://jenkins.example.test"}
    for name in SERVICE_ONLY_TOOLS:
        assert tool_visibility_decision(name, config).visible is False
    offered = {definition["function"]["name"] for definition in get_tool_definitions("diagnosis")}
    assert offered & SERVICE_ONLY_TOOLS == set()
    assert set(catalog_tool_names()) & SERVICE_ONLY_TOOLS == set()

    context = ToolContext(user_id="u", project_ids=["p"], roles=[], session_id="s", project_config=config)
    found = await execute_tool_search({"query": "jenkins builds", "limit": 50}, context)
    assert {tool["name"] for tool in found["tools"]} & SERVICE_ONLY_TOOLS == set()
    refused = await execute_tool("list_jenkins_builds", {}, context)
    assert refused["policy"] == "service_only_connector"


@pytest.mark.parametrize(("preset_name", "connector"), sorted(_PRESET_CONNECTOR.items()))
def test_activation_keys_cover_every_preset_field(preset_name, connector):
    fields = {
        field for field in TOOL_CONFIG_PRESETS[preset_name]["fields"] if not field.startswith("knowledge_import_")
    }
    assert sorted(fields - set(CONNECTOR_CONFIG_KEYS[connector])) == []


@pytest.mark.parametrize("preset_name", sorted(TOOL_CONFIG_PRESETS))
def test_a_project_configured_from_a_preset_keeps_the_preset_tools(preset_name):
    preset = TOOL_CONFIG_PRESETS[preset_name]
    owned_preset_tools = [tool["name"] for tool in preset.get("tools", []) if tool["name"] in CONNECTOR_BY_OWNED_TOOL]
    hidden = [
        tool_name
        for tool_name in owned_preset_tools
        if not tool_visibility_decision(tool_name, dict(preset["example"])).visible
    ]
    assert hidden == []


def test_connector_owned_tools_are_hidden_without_connector_activation():
    visible = sorted(name for name in CONNECTOR_BY_OWNED_TOOL if tool_visibility_decision(name, {}).visible)
    assert visible == []


def test_a_configured_connector_write_still_needs_its_exact_high_risk_grant():
    project_config = dict(TOOL_CONFIG_PRESETS["helm"]["example"])
    assert tool_visibility_decision("upgrade", project_config).visible is True

    denied = tool_project_policy_decision("upgrade", project_config)
    assert (denied.allowed, denied.reason) == (False, "high_risk_tool_requires_explicit_allow")

    granted_config = {**project_config, "tool_policy": {"high_risk_grants": ["upgrade"]}}
    granted = tool_project_policy_decision("upgrade", granted_config)
    assert (granted.allowed, granted.matched_rule) == (True, "high_risk_grants")
    assert tool_project_policy_decision("rollback", granted_config).allowed is False
    assert tool_project_policy_decision("list_releases", project_config).allowed is True


def test_composite_connector_follows_its_members_and_its_own_explicit_state():
    assert connector_activation_decision("ci_pipelines", {"enabled_connectors": ["github"]}) == (
        True,
        "member_connector_active",
        "github:enabled_connectors",
    )
    assert connector_activation_decision("ci_pipelines", {"github_token": "configured"}) == (
        True,
        "project_connector_config_present",
        "github_token",
    )
    assert connector_activation_decision(
        "ci_pipelines",
        {"github_url": "https://github.example.test", "disabled_connectors": ["ci_pipelines"]},
    ) == (False, "explicit_connector_deactivation", "disabled_connectors")
    assert connector_activation_decision("newrelic_splunk_alerts", {"splunk_url": "https://splunk.example.test"})[0]
    assert connector_activation_decision("sonarqube_linear_issues", {}) == (
        False,
        "connector_not_active_for_project",
        "connector:sonarqube_linear_issues",
    )


def test_new_connectors_accept_their_admin_preset_name_as_explicit_activation():
    assert connector_activation_decision("outlook", {"enabled_connectors": ["outlook_calendar"]})[0] is True
    assert connector_activation_decision("docker_registry", {"connectors": {"docker_registry": True}})[0] is True
    assert connector_activation_decision("vault", {"vault_enabled": False, "vault_url": "https://vault.test"}) == (
        False,
        "explicit_connector_deactivation",
        "vault_enabled",
    )


def test_no_connector_preset_offers_the_generic_http_tools_as_its_own() -> None:
    from app.services.tool_config import get_default_connector_for_tool
    from app.services.tool_config.presets import TOOL_CONFIG_PRESETS

    for name, preset in TOOL_CONFIG_PRESETS.items():
        offered = {tool.get("name") for tool in preset.get("tools", [])}
        assert not offered & {"http_request", "web_fetch"}, name
    assert get_default_connector_for_tool("http_request") is None
    assert get_default_connector_for_tool("web_fetch") is None
