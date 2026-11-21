"""Connector ownership for connector tools whose definitions live in shared modules.

The Atlassian, source-control, cloud and incident tools get their connector from
the definition module they are declared in (``definitions/__init__.py``). The tools
below are implemented under ``tools/connectors/`` (and Grafana under
``tools/grafana.py``) but declared in cross-domain definition modules (``cicd``,
``infrastructure``, ``observability`` ...), so their owner is stated here, by name.

Owning a tool through a connector means (``get_tool_definition_metadata``):

- ``owner_type="connector"`` and ``connector=<name>``;
- the tool is visible and dispatchable only when the connector is active for the
  project (``tools/visibility.py``, keys in ``tools/connector_activation_catalog.py``);
- a ``write``/``admin`` tool needs an exact-name ``high_risk_grants`` entry
  (``services/tool_access_policy.py``) and the ``deliver`` run capability (unless
  ``tools/capability_requirements.py`` lists it as read-only compatible).

Some tools serve several providers at once. They belong to a composite connector
(``ci_pipelines``, ``sonarqube_linear_issues``, ``newrelic_splunk_alerts``) that is
active when it is activated itself or when any of its member connectors is active,
see ``COMPOSITE_CONNECTOR_MEMBERS`` in the activation catalog.
"""

from __future__ import annotations

CONNECTOR_TOOL_OWNERSHIP: dict[str, tuple[str, ...]] = {
    # Infrastructure as code and deployment
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
    # Cloud databases
    "gcp": ("get_gcp_cloud_sql_metrics", "list_gcp_cloud_sql_instances"),
    # Secrets and identity
    "vault": ("audit_log_read", "list_secrets", "read_secret", "renew_lease", "revoke_token"),
    "ldap": ("check_membership", "get_groups", "search_user", "sync_users", "user_provisioning"),
    # Observability
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
    # Status pages
    "statuspage": ("list_components", "update_component_status"),
    # Code quality and security
    "snyk": ("get_fix_advice", "get_severity", "list_vulnerabilities"),
    "sonarqube": ("get_project_metrics", "get_quality_gate"),
    # SonarQube or Linear issues (composite)
    "sonarqube_linear_issues": ("list_issues",),
    # Ticketing, IT service management, documents, calendars
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
