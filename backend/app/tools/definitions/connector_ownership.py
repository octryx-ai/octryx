"""Connector ownership for connector tools whose definitions live in shared modules."""

from __future__ import annotations

CONNECTOR_TOOL_OWNERSHIP: dict[str, tuple[str, ...]] = {
    "ansible": ("check_mode", "get_facts", "get_job_output", "list_inventory", "run_playbook"),
    "argocd": (
        "get_app_status",
        "get_rollout_status",
        "list_apps",
        "list_events",
        "rollback_app",
        "sync_app",
    ),
    "helm": ("get_history", "get_status", "list_releases", "rollback", "upgrade"),
    "terraform": ("apply", "get_output", "list_resources", "plan", "show_state", "workspace_select"),
    "docker_registry": ("delete_tag", "get_image_vulnerabilities", "list_repositories", "list_tags"),
    # CI across GitHub Actions, GitLab CI and Azure DevOps (composite)
    "ci_pipelines": (
        "cancel_pipeline",
        "get_artifact",
        "get_job_logs",
        "get_pipeline_logs",
        "get_test_results",
        "list_artifacts",
        "retry_job",
        "trigger_workflow",
    ),
    "azure_devops": ("list_pipelines", "list_work_items"),
    # Jenkins builds of the alert target's job, through the Workspace's ``jenkins`` named connection
    "jenkins": ("list_jenkins_builds",),
    "gcp": ("get_gcp_cloud_sql_metrics", "list_gcp_cloud_sql_instances"),
    "vault": ("audit_log_read", "list_secrets", "read_secret", "renew_lease", "revoke_token"),
    "ldap": ("check_membership", "get_groups", "search_user", "sync_users", "user_provisioning"),
    "datadog": ("get_apm_traces", "get_events", "get_service_map", "list_monitors", "query_metrics"),
    "elasticsearch": ("get_elasticsearch_cluster_health", "search_elasticsearch_documents"),
    "grafana": (
        "create_snapshot",
        "get_dashboard_json",
        "list_grafana_alerts",
        "read_grafana_alert",
        "render_panel_as_image",
    ),
    "newrelic": ("get_apm_data", "nrql_query"),
    "splunk": ("get_index_stats", "get_saved_searches", "search_logs"),
    # New Relic or Splunk alerts (composite)
    "newrelic_splunk_alerts": ("get_alerts",),
    "statuspage": ("list_components", "update_component_status"),
    "snyk": ("get_fix_advice", "get_severity", "list_vulnerabilities"),
    "sonarqube": ("get_project_metrics", "get_quality_gate"),
    # SonarQube or Linear issues (composite)
    "sonarqube_linear_issues": ("list_issues",),
    "linear": ("create_issue", "update_issue"),
    "servicenow": ("get_servicenow_record", "list_servicenow_changes", "list_servicenow_records"),
    "notion": ("get_notion_page", "search_notion_pages"),
    "sharepoint": ("list_sharepoint_site_pages", "search_sharepoint"),
    "outlook": (
        "check_absence",
        "create_meeting",
        "find_next_slot",
        "get_free_busy",
        "list_meetings",
        "send_meeting_invite",
    ),
}


def _connector_by_owned_tool() -> dict[str, str]:
    owners: dict[str, str] = {}
    for connector, tool_names in CONNECTOR_TOOL_OWNERSHIP.items():
        for tool_name in tool_names:
            if tool_name in owners:
                raise ValueError(f"Tool {tool_name} is owned by both {owners[tool_name]} and {connector}")
            owners[tool_name] = connector
    return owners


CONNECTOR_BY_OWNED_TOOL: dict[str, str] = _connector_by_owned_tool()

# Owners whose connection serves platform services only (``named_connections.descriptors.SERVICE_ONLY_CONNECTORS``):
# they have no activation path, so their tools stay defined but are never offered to chat or agents.
SERVICE_ONLY_TOOL_CONNECTORS = frozenset({"jenkins"})
SERVICE_ONLY_TOOLS = frozenset(
    tool_name for tool_name, connector in CONNECTOR_BY_OWNED_TOOL.items() if connector in SERVICE_ONLY_TOOL_CONNECTORS
)

__all__ = ["CONNECTOR_BY_OWNED_TOOL", "CONNECTOR_TOOL_OWNERSHIP", "SERVICE_ONLY_TOOLS", "SERVICE_ONLY_TOOL_CONNECTORS"]
