"""Which connector read tools are evidence-bearing, and why the rest are not.

Every connector read tool in the registry (an entry with a ``connector`` that does not mutate
state) is in exactly one of three tables, which ``tests/test_connector_evidence_coverage.py`` holds
against the live registry:

- :data:`SOURCED_CONNECTOR_READS`: its items carry ``source_title`` / ``source_url`` / ``cite_as``
  (``tools/evidence_fields.py``) from the connector's configured base URL, so the answer evidence
  guard checks answers built on them. The test runs each one and asserts the fields.
- :data:`WEB_URL_LINKED_CONNECTOR_READS`: tool name -> the optional ``<connector>_web_url`` config
  field (``services/tool_config/web_url.py``). Linked when the administrator configured that web URL
  (``tools/connectors/web_url_sources.py``); without it the read carries no fields and an answer built
  only on it is ``unsourced``. The test runs each one with and without the field.
- :data:`UNSOURCED_CONNECTOR_READS`: tool name -> a closed reason from :data:`UNSOURCED_REASONS`. Its
  results have no openable item page, so they never carry fields.

A new connector read tool fails that test until it is added to one table.
"""

from __future__ import annotations

from app.services.tool_config.web_url import OPSGENIE_WEB_URL_FIELD, WEB_URL_FIELDS
from app.tools.connectors.web_url_sources import WEB_URL_LINKERS

UNSOURCED_REASONS: dict[str, str] = {
    "aggregate_report": (
        "A multi-resource analysis or report (topology, exposure, drift, posture, cost, timeline): it has no "
        "single item page; the resources it names are cited through the cloud list tools."
    ),
    "metrics_or_logs": (
        "Metric series, aggregates, log or search text, or test reports: there is no item page to open."
    ),
    "runtime_command_output": (
        "Output of a command run on the platform runtime (Ansible, Terraform, Helm): no web page exists."
    ),
    "secret_material": "Secret values and secret metadata are never linked or cited.",
    "directory_and_people": (
        "Directory, user and calendar lookups describe people, not citable documents (LDAP, user search, "
        "free/busy)."
    ),
    "configuration_metadata": (
        "Connector configuration metadata (issue types, priorities, transitions, sprints): no item page."
    ),
    "api_only_resource": (
        "Registry, search-index, artifact or diff-range API objects without a web page on the configured host."
    ),
}

SOURCED_CONNECTOR_READS: frozenset[str] = frozenset(
    {
        # Jira
        "search_jira_tickets",
        "get_jira_ticket",
        "get_sprint_issues",
        "list_jira_versions",
        "list_jira_projects",
        "list_jira_boards",
        "jira_release_status",
        # Confluence
        "search_confluence",
        "get_confluence_page",
        "list_confluence_pages",
        # Bitbucket Server
        "list_bitbucket_repositories",
        "read_bitbucket_file",
        "list_bitbucket_directory",
        "list_bitbucket_branches",
        "list_bitbucket_pull_requests",
        "get_bitbucket_pull_request",
        "list_bitbucket_commits",
        "list_recent_bitbucket_commits",
        "get_bitbucket_commit_changes",
        "get_bitbucket_diff",
        # GitHub
        "list_github_repositories",
        "list_github_branches",
        "list_github_pull_requests",
        "get_github_pull_request",
        "list_github_issues",
        "get_github_issue",
        "read_github_file",
        "list_github_action_runs",
        # GitLab
        "list_gitlab_projects",
        "list_gitlab_branches",
        "list_gitlab_merge_requests",
        "get_gitlab_merge_request",
        "list_gitlab_pipelines",
        "read_gitlab_file",
        # ServiceNow
        "list_servicenow_records",
        "get_servicenow_record",
        "list_servicenow_incidents",
        "list_servicenow_changes",
        # Notion, SharePoint, Linear / SonarQube, Azure DevOps
        "search_notion_pages",
        "get_notion_page",
        "search_sharepoint",
        "list_sharepoint_site_pages",
        "list_issues",
        "get_project_metrics",
        "get_quality_gate",
        "list_work_items",
        "list_pipelines",
        # Grafana, ArgoCD
        "list_grafana_alerts",
        "read_grafana_alert",
        "get_dashboard_json",
        "render_panel_as_image",
        "list_apps",
        "get_app_status",
        "get_rollout_status",
        "list_events",
    }
)

_AGGREGATE = "aggregate_report"
_METRICS = "metrics_or_logs"
_RUNTIME = "runtime_command_output"
_PEOPLE = "directory_and_people"
_META = "configuration_metadata"
_API = "api_only_resource"

# The web URL field each linker reads; incident tools read PagerDuty's or Opsgenie's by provider.
_INCIDENT_FIELDS = f"{WEB_URL_FIELDS['pagerduty']}|{OPSGENIE_WEB_URL_FIELD}"
_LINKER_FIELDS: dict[str, str] = {
    "list_monitors": WEB_URL_FIELDS["datadog"],
    "get_events": WEB_URL_FIELDS["datadog"],
    "get_alerts": WEB_URL_FIELDS["newrelic"],
    "list_vulnerabilities": WEB_URL_FIELDS["snyk"],
    "get_severity": WEB_URL_FIELDS["snyk"],
    "get_fix_advice": WEB_URL_FIELDS["snyk"],
    "get_schedule": _INCIDENT_FIELDS,
    "get_escalation_policy": _INCIDENT_FIELDS,
    "list_oncall": _INCIDENT_FIELDS,
    "list_components": WEB_URL_FIELDS["statuspage"],
}
_CLOUDS = ("aws", "azure", "gcp")


def _linker_field(name: str) -> str:
    """The console field of a cloud list tool (its name names the cloud), else the table above."""
    cloud = next((cloud for cloud in _CLOUDS if f"_{cloud}_" in f"_{name}_"), None)
    return WEB_URL_FIELDS[cloud] if cloud else _LINKER_FIELDS[name]


WEB_URL_LINKED_CONNECTOR_READS: dict[str, str] = {name: _linker_field(name) for name in WEB_URL_LINKERS}

UNSOURCED_CONNECTOR_READS: dict[str, str] = {
    # Multi-resource analyses and reports.
    **{
        name: _AGGREGATE
        for name in (
            "aws_config_query",
            "aws_cost_topology_report",
            "aws_deployment_timeline",
            "aws_exposure_map",
            "aws_incident_evidence_bundle",
            "aws_network_path_analyzer",
            "aws_read_operation",
            "aws_runtime_vs_iac_drift",
            "aws_security_posture_summary",
            "aws_topology_diff",
            "aws_topology_snapshot",
            "aws_trusted_advisor_summary",
            "aws_well_architected_assessment",
        )
    },
    # Metric series, aggregates, logs, search text and reports.
    **{
        name: _METRICS
        for name in (
            "get_aws_cost_by_service",
            "get_aws_ec2_logs",
            "get_aws_lambda_logs",
            "get_aws_rds_metrics",
            "get_aws_rds_slow_queries",
            "search_aws_cloudtrail_events",
            "get_azure_cost",
            "get_azure_monitor_alerts",
            "get_azure_monitor_metrics",
            "get_gcp_cloud_run_logs",
            "get_gcp_cloud_sql_metrics",
            "get_gcp_compute_logs",
            "query_metrics",
            "get_apm_traces",
            "get_service_map",
            "nrql_query",
            "get_apm_data",
            "search_logs",
            "get_index_stats",
            "get_saved_searches",
            "get_job_logs",
            "get_pipeline_logs",
            "get_test_results",
            "list_jenkins_builds",
            # CI build states (and Pipelines test reports) of a commit; each links to the CI system, not to
            # a page on the Bitbucket host.
            "get_bitbucket_build_statuses",
            "get_gitlab_commit_checks",
            "get_elasticsearch_cluster_health",
        )
    },
    # Command output on the platform runtime.
    **{
        name: _RUNTIME
        for name in (
            "check_mode",
            "get_facts",
            "get_job_output",
            "list_inventory",
            "get_output",
            "list_resources",
            "plan",
            "show_state",
            "get_history",
            "get_status",
            "list_releases",
        )
    },
    # Secrets.
    "audit_log_read": "secret_material",
    "list_secrets": "secret_material",
    "read_secret": "secret_material",
    # People and calendars.
    **{
        name: _PEOPLE
        for name in (
            "check_membership",
            "get_groups",
            "search_user",
            "search_jira_users",
            "search_bitbucket_users",
            "check_absence",
            "find_next_slot",
            "get_free_busy",
            "list_meetings",
        )
    },
    # Connector configuration metadata.
    **{
        name: _META
        for name in ("list_jira_issue_types", "list_jira_priorities", "list_jira_transitions", "list_jira_sprints")
    },
    # API objects without a web page on the configured host.
    **{
        name: _API
        for name in (
            "list_repositories",
            "list_tags",
            "get_image_vulnerabilities",
            "search_elasticsearch_documents",
            "list_artifacts",
            "get_artifact",
            # The PR review bot's hourly sync reads open heads for itself; agents cite the pull request tools.
            "list_github_pull_request_heads",
            "get_github_commit_checks",
            "list_bitbucket_pull_request_heads",
            "list_gitlab_merge_request_heads",
        )
    },
}

__all__ = [
    "SOURCED_CONNECTOR_READS",
    "UNSOURCED_CONNECTOR_READS",
    "UNSOURCED_REASONS",
    "WEB_URL_LINKED_CONNECTOR_READS",
]
