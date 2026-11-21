"""The admin panel manages the connector policy and the tool catalog."""

import pytest
from sqlalchemy import select

from app.models import ConnectorHealth, ConnectorHealthLog, ConnectorPolicy
from tests.conftest import ADMIN_PASSWORD

# Every connector the panel must list (tool names, in the order the test checks them).
_CONNECTOR_TOOL_NAMES = (
    "github", "gitlab", "notion", "sharepoint", "grafana", "elasticsearch", "aws", "azure", "gcp", "argocd",
    "terraform", "vault", "sonarqube", "snyk", "ansible", "datadog", "newrelic", "linear", "azure_devops",
    "statuspage", "helm", "docker_registry", "splunk", "ldap", "outlook_calendar", "system", "jenkins",
    "pagerduty", "servicenow", "postgres",
)


def _connector(connectors, tool_name):
    return next((item for item in connectors if item["tool_name"] == tool_name), None)


async def _seed_github_health(db) -> ConnectorHealthLog:
    db.add(
        ConnectorHealth(
            connector_name="github",
            project_id="",
            status="ok",
            response_time_ms=123,
            error=None,
            details="GitHub API reachable",
        )
    )
    health_log = ConnectorHealthLog(
        connector_name="github",
        project_id="",
        status="ok",
        response_time_ms=123,
        error=None,
        details="GitHub API reachable",
    )
    db.add(health_log)
    await db.commit()
    return health_log


def _assert_connectors_listed(listed, connectors) -> None:
    assert listed["github"] is not None
    assert listed["gitlab"] is not None
    assert listed["notion"] is not None
    assert listed["sharepoint"] is not None
    assert listed["grafana"] is not None
    assert listed["elasticsearch"] is not None
    assert listed["aws"] is not None
    assert listed["azure"] is not None
    assert listed["gcp"] is not None
    assert listed["argocd"] is not None
    assert listed["terraform"] is not None
    assert listed["vault"] is not None
    assert listed["sonarqube"] is not None
    assert listed["snyk"] is not None
    assert listed["ansible"] is not None
    assert listed["datadog"] is not None
    assert listed["newrelic"] is not None
    assert listed["linear"] is not None
    assert listed["azure_devops"] is not None
    assert listed["statuspage"] is not None
    assert listed["helm"] is not None
    assert listed["docker_registry"] is not None
    assert listed["splunk"] is not None
    assert listed["ldap"] is not None
    assert listed["outlook_calendar"] is not None
    assert listed["system"] is not None
    assert listed["jenkins"] is not None
    assert all(item["tool_name"] != "nexus" for item in connectors)
    assert listed["pagerduty"] is not None
    assert listed["servicenow"] is not None
    assert listed["postgres"] is not None


def _assert_connector_fields(listed) -> None:
    assert listed["github"]["health"]["status"] == "ok"
    assert listed["github"]["health"]["response_time_ms"] == 123
    assert "github_url" in listed["github"]["fields"]
    assert "gitlab_url" in listed["gitlab"]["fields"]
    assert "notion_token" in listed["notion"]["fields"]
    assert "sharepoint_url" in listed["sharepoint"]["fields"]
    assert "grafana_url" in listed["grafana"]["fields"]
    assert "elasticsearch_url" in listed["elasticsearch"]["fields"]
    assert "aws_region" in listed["aws"]["fields"]
    assert "aws_access_key_id" in listed["aws"]["fields"]
    assert "aws_secret_access_key" in listed["aws"]["fields"]
    assert "aws_session_token" in listed["aws"]["fields"]
    assert listed["aws"]["secret_fields"] == ["aws_access_key_id", "aws_secret_access_key", "aws_session_token"]
    assert listed["aws"]["supports_test"] is True
    assert "azure_tenant_id" in listed["azure"]["fields"]
    assert "gcp_project_id" in listed["gcp"]["fields"]
    assert "argocd_url" in listed["argocd"]["fields"]
    assert "terraform_root" in listed["terraform"]["fields"]
    assert "vault_url" in listed["vault"]["fields"]
    assert "sonarqube_url" in listed["sonarqube"]["fields"]
    assert "snyk_url" in listed["snyk"]["fields"]
    assert "ansible_inventory_path" in listed["ansible"]["fields"]
    assert "datadog_url" in listed["datadog"]["fields"]
    assert "newrelic_account_id" in listed["newrelic"]["fields"]
    assert "linear_api_key" in listed["linear"]["fields"]
    assert "azure_devops_pat" in listed["azure_devops"]["fields"]
    assert "statuspage_page_id" in listed["statuspage"]["fields"]
    assert "helm_binary" in listed["helm"]["fields"]
    assert "docker_registry_url" in listed["docker_registry"]["fields"]
    assert "splunk_url" in listed["splunk"]["fields"]
    assert "ldap_server_url" in listed["ldap"]["fields"]
    assert "outlook_default_mailbox" in listed["outlook_calendar"]["fields"]


def _assert_code_and_cloud_connector_tools(listed) -> None:
    assert any(tool["name"] == "list_github_repositories" for tool in listed["github"]["tools"])
    assert any(tool["name"] == "get_job_logs" for tool in listed["github"]["tools"])
    assert any(tool["name"] == "trigger_workflow" for tool in listed["github"]["tools"])
    assert any(tool["name"] == "list_gitlab_projects" for tool in listed["gitlab"]["tools"])
    assert any(tool["name"] == "get_pipeline_logs" for tool in listed["gitlab"]["tools"])
    assert any(tool["name"] == "get_test_results" for tool in listed["gitlab"]["tools"])
    assert any(tool["name"] == "search_notion_pages" for tool in listed["notion"]["tools"])
    assert any(tool["name"] == "list_sharepoint_site_pages" for tool in listed["sharepoint"]["tools"])
    assert any(tool["name"] == "read_grafana_alert" for tool in listed["grafana"]["tools"])
    assert any(tool["name"] == "list_grafana_alerts" for tool in listed["grafana"]["tools"])
    assert any(tool["name"] == "render_panel_as_image" for tool in listed["grafana"]["tools"])
    assert any(tool["name"] == "create_snapshot" for tool in listed["grafana"]["tools"])
    assert any(tool["name"] == "get_dashboard_json" for tool in listed["grafana"]["tools"])
    assert any(tool["name"] == "get_elasticsearch_cluster_health" for tool in listed["elasticsearch"]["tools"])
    assert any(tool["name"] == "list_aws_eks_clusters" for tool in listed["aws"]["tools"])
    assert any(tool["name"] == "list_aws_ec2_instances" for tool in listed["aws"]["tools"])
    assert any(tool["name"] == "invoke_aws_lambda" for tool in listed["aws"]["tools"])
    assert any(tool["name"] == "get_aws_cost_by_service" for tool in listed["aws"]["tools"])
    assert any(tool["name"] == "list_azure_resource_groups" for tool in listed["azure"]["tools"])
    assert any(tool["name"] == "list_azure_vms" for tool in listed["azure"]["tools"])
    assert any(tool["name"] == "get_azure_cost" for tool in listed["azure"]["tools"])
    assert any(tool["name"] == "list_gcp_projects" for tool in listed["gcp"]["tools"])
    assert any(tool["name"] == "list_gcp_compute_instances" for tool in listed["gcp"]["tools"])
    assert any(tool["name"] == "list_gcp_cloud_run_services" for tool in listed["gcp"]["tools"])
    assert any(tool["name"] == "list_apps" for tool in listed["argocd"]["tools"])
    assert any(tool["name"] == "rollback_app" for tool in listed["argocd"]["tools"])
    assert any(tool["name"] == "plan" for tool in listed["terraform"]["tools"])
    assert any(tool["name"] == "workspace_select" for tool in listed["terraform"]["tools"])
    assert any(tool["name"] == "read_secret" for tool in listed["vault"]["tools"])
    assert any(tool["name"] == "audit_log_read" for tool in listed["vault"]["tools"])
    assert any(tool["name"] == "get_project_metrics" for tool in listed["sonarqube"]["tools"])
    assert any(tool["name"] == "get_quality_gate" for tool in listed["sonarqube"]["tools"])
    assert any(tool["name"] == "list_vulnerabilities" for tool in listed["snyk"]["tools"])
    assert any(tool["name"] == "get_fix_advice" for tool in listed["snyk"]["tools"])
    assert any(tool["name"] == "run_playbook" for tool in listed["ansible"]["tools"])
    assert any(tool["name"] == "get_job_output" for tool in listed["ansible"]["tools"])


def _assert_ops_connector_tools(listed) -> None:
    assert any(tool["name"] == "query_metrics" for tool in listed["datadog"]["tools"])
    assert any(tool["name"] == "get_service_map" for tool in listed["datadog"]["tools"])
    assert any(tool["name"] == "nrql_query" for tool in listed["newrelic"]["tools"])
    assert any(tool["name"] == "get_apm_data" for tool in listed["newrelic"]["tools"])
    assert any(tool["name"] == "list_issues" for tool in listed["linear"]["tools"])
    assert any(tool["name"] == "create_issue" for tool in listed["linear"]["tools"])
    assert any(tool["name"] == "update_issue" for tool in listed["linear"]["tools"])
    assert any(tool["name"] == "list_work_items" for tool in listed["azure_devops"]["tools"])
    assert any(tool["name"] == "list_pipelines" for tool in listed["azure_devops"]["tools"])
    assert any(tool["name"] == "get_pipeline_logs" for tool in listed["azure_devops"]["tools"])
    assert any(tool["name"] == "create_incident" for tool in listed["statuspage"]["tools"])
    assert any(tool["name"] == "update_incident" for tool in listed["statuspage"]["tools"])
    assert any(tool["name"] == "resolve_incident" for tool in listed["statuspage"]["tools"])
    assert any(tool["name"] == "list_components" for tool in listed["statuspage"]["tools"])
    assert any(tool["name"] == "update_component_status" for tool in listed["statuspage"]["tools"])
    assert any(tool["name"] == "list_releases" for tool in listed["helm"]["tools"])
    assert any(tool["name"] == "get_status" for tool in listed["helm"]["tools"])
    assert any(tool["name"] == "get_history" for tool in listed["helm"]["tools"])
    assert any(tool["name"] == "upgrade" for tool in listed["helm"]["tools"])
    assert any(tool["name"] == "rollback" for tool in listed["helm"]["tools"])
    assert any(tool["name"] == "list_repositories" for tool in listed["docker_registry"]["tools"])
    assert any(tool["name"] == "list_tags" for tool in listed["docker_registry"]["tools"])
    assert any(tool["name"] == "get_image_vulnerabilities" for tool in listed["docker_registry"]["tools"])
    assert any(tool["name"] == "delete_tag" for tool in listed["docker_registry"]["tools"])
    assert any(tool["name"] == "search_logs" for tool in listed["splunk"]["tools"])
    assert any(tool["name"] == "get_saved_searches" for tool in listed["splunk"]["tools"])
    assert any(tool["name"] == "get_alerts" for tool in listed["splunk"]["tools"])
    assert any(tool["name"] == "get_index_stats" for tool in listed["splunk"]["tools"])
    assert any(tool["name"] == "search_user" for tool in listed["ldap"]["tools"])
    assert any(tool["name"] == "user_provisioning" for tool in listed["ldap"]["tools"])
    assert any(tool["name"] == "get_free_busy" for tool in listed["outlook_calendar"]["tools"])
    assert any(tool["name"] == "send_meeting_invite" for tool in listed["outlook_calendar"]["tools"])
    assert any(tool["name"] == "bash" for tool in listed["system"]["tools"])
    assert "jenkins_url" in listed["jenkins"]["fields"]
    assert listed["jenkins"]["tools"] == []  # serves platform CI only; no chat tool
    assert "incident_provider" in listed["pagerduty"]["fields"]
    assert "opsgenie_url" in listed["pagerduty"]["fields"]
    assert any(tool["name"] == "create_incident" for tool in listed["pagerduty"]["tools"])
    assert any(tool["name"] == "list_oncall" for tool in listed["pagerduty"]["tools"])
    assert "servicenow_url" in listed["servicenow"]["fields"]
    assert "servicenow_client_id" in listed["servicenow"]["fields"]
    assert any(tool["name"] == "list_servicenow_incidents" for tool in listed["servicenow"]["tools"])
    assert "postgres_host" in listed["postgres"]["fields"]


async def _assert_tool_catalog(client) -> None:
    catalog_resp = await client.get("/admin/chat/api/panel/tool-catalog")
    assert catalog_resp.status_code == 200
    catalog = catalog_resp.json()
    catalog_by_name = {entry["name"]: entry for entry in catalog}
    assert any(entry["name"] == "bash" and entry["default_connector"] == "system" for entry in catalog)
    assert catalog_by_name["bash"]["connectors"] == []
    assert any(entry["name"] == "list_mcp_servers" and entry["default_connector"] is None for entry in catalog)
    assert catalog_by_name["list_mcp_servers"]["connectors"] == []
    assert any(entry["name"] == "http_request" and entry["default_connector"] is None for entry in catalog)
    assert "list_github_action_runs" not in catalog_by_name
    assert "list_oncall" not in catalog_by_name
    assert "create_incident" not in catalog_by_name


async def _assert_system_connector_policy_update(client, db) -> None:
    update_resp = await client.put(
        "/admin/chat/api/panel/connectors/system",
        json={
            "is_active": True,
            "tool_policy": {
                "tool_instructions": "Prefer read-only workspace inspection before shell execution.",
                "extra_tools": ["todo_read"],
                "disabled_tools": ["run_cli_command"],
            },
            "policy_active": True,
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["tool_policy"]["tool_instructions"].startswith("Prefer read-only")
    assert "todo_read" in updated["tool_policy"]["extra_tools"]
    assert any(tool["name"] == "todo_read" for tool in updated["tools"])
    assert all(tool["name"] != "run_cli_command" for tool in updated["tools"])

    stored = (
        await db.execute(select(ConnectorPolicy).where(ConnectorPolicy.connector_name == "system"))
    ).scalar_one_or_none()
    assert stored is not None
    assert stored.policy["disabled_tools"] == ["run_cli_command"]


async def _assert_github_health_history(client, health_log) -> None:
    health_history_resp = await client.get("/admin/chat/api/panel/connectors/github/health-log")
    assert health_history_resp.status_code == 200
    health_history = health_history_resp.json()
    assert len(health_history) == 1
    assert health_history[0]["id"] == health_log.id
    assert health_history[0]["status"] == "ok"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_panel_can_manage_connector_policy_and_tool_catalog(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    health_log = await _seed_github_health(db)

    connectors_resp = await client.get("/admin/chat/api/panel/connectors")
    assert connectors_resp.status_code == 200
    connectors = connectors_resp.json()
    listed = {tool_name: _connector(connectors, tool_name) for tool_name in _CONNECTOR_TOOL_NAMES}
    _assert_connectors_listed(listed, connectors)
    _assert_connector_fields(listed)
    _assert_code_and_cloud_connector_tools(listed)
    _assert_ops_connector_tools(listed)

    await _assert_tool_catalog(client)
    await _assert_system_connector_policy_update(client, db)
    await _assert_github_health_history(client, health_log)
