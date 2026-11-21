"""Tests for tool registry, tool definitions, MCP bridge, build system prompt, and code search tools."""

from app.tools.registry import (
    TOOL_REGISTRY,
    TOOL_REGISTRY_ENTRIES,
    get_tool_registry_entry,
    get_tool_registry_owner_summary,
    list_tool_registry_entries,
)

EXPECTED_TOOL_NAMES = [
    "read_grafana_alert",
    "list_grafana_alerts",
    "render_panel_as_image",
    "create_snapshot",
    "get_dashboard_json",
    "query_prometheus",
    "query_loki",
    "get_k8s_events",
    "get_pod_logs",
    "list_failed_pods",
    "get_k8s_deployments",
    "search_jira_tickets",
    "get_jira_ticket",
    "list_jira_transitions",
    "transition_jira_ticket",
    "add_jira_comment",
    "get_system_context",
    "get_current_time",
    "list_bitbucket_repositories",
    "list_bitbucket_directory",
    "read_bitbucket_file",
    "list_bitbucket_commits",
    "list_recent_bitbucket_commits",
    "get_bitbucket_commit_changes",
    "prepare_bitbucket_repository",
    "commit_and_push_repository_branch",
    "list_confluence_pages",
    "get_confluence_page",
    "http_request",
    "run_cli_command",
    "write_workspace_file",
    "list_workspace_directory",
    "read_workspace_file",
    "analyze_workspace_repository",
    "code_node",
    "code_neighbors",
    "code_trace",
    "code_graph_stats",
    "code_graph_status",
    "code_god_nodes",
    "code_affected",
    "code_impact",
    "code_callees",
    "code_files",
    "code_context",
    "code_explore",
    "list_repository_readme_status",
    "generate_repository_readmes",
    "list_workspace_git_commits",
    "run_kubectl",
    "save_python_script",
    "list_saved_python_scripts",
    "get_saved_python_script",
    "run_saved_python_script",
    "list_github_repositories",
    "list_github_pull_requests",
    "list_github_action_runs",
    "get_job_logs",
    "get_pipeline_logs",
    "trigger_workflow",
    "retry_job",
    "cancel_pipeline",
    "list_artifacts",
    "get_artifact",
    "get_test_results",
    "read_secret",
    "list_secrets",
    "renew_lease",
    "revoke_token",
    "audit_log_read",
    "get_project_metrics",
    "list_issues",
    "create_issue",
    "update_issue",
    "list_work_items",
    "list_pipelines",
    "get_quality_gate",
    "list_vulnerabilities",
    "get_severity",
    "get_fix_advice",
    "list_gitlab_projects",
    "list_gitlab_merge_requests",
    "list_gitlab_pipelines",
    "search_notion_pages",
    "get_notion_page",
    "search_sharepoint",
    "list_sharepoint_site_pages",
    "list_servicenow_records",
    "get_servicenow_record",
    "list_servicenow_incidents",
    "list_servicenow_changes",
    "get_elasticsearch_cluster_health",
    "search_elasticsearch_documents",
    "list_aws_eks_clusters",
    "list_aws_cloudwatch_alarms",
    "list_azure_resource_groups",
    "list_azure_aks_clusters",
    "list_gcp_projects",
    "list_gcp_gke_clusters",
]


def test_tool_registry_has_all_tools():
    assert len(TOOL_REGISTRY) >= 121
    for tool_name in EXPECTED_TOOL_NAMES:
        assert tool_name in TOOL_REGISTRY


def test_tool_registry_reports_owner_metadata_for_registered_tools():
    jira_entry = get_tool_registry_entry("search_jira_tickets")
    assert jira_entry is not None
    assert jira_entry["owner_type"] == "connector"
    assert jira_entry["source"] == "connector"
    assert jira_entry["connector"] == "jira"
    assert jira_entry["implementation_module"].startswith("app.tools.jira")

    github_entry = get_tool_registry_entry("create_github_repository")
    assert github_entry is not None
    assert github_entry["owner_type"] == "connector"
    assert github_entry["connector"] == "github"
    assert github_entry["risk"] == "write"

    workspace_entry = get_tool_registry_entry("read_workspace_file")
    assert workspace_entry is not None
    assert workspace_entry["owner_type"] == "built_in"
    assert workspace_entry["source"] == "base"
    assert workspace_entry["connector"] is None


def test_tool_registry_can_filter_connector_owned_tools():
    jira_tools = list_tool_registry_entries(owner_type="connector", connector="jira")
    jira_names = {entry["name"] for entry in jira_tools}

    assert "search_jira_tickets" in jira_names
    assert "create_jira_ticket" in jira_names
    assert "read_workspace_file" not in jira_names
    assert all(entry["owner_type"] == "connector" for entry in jira_tools)
    assert all(entry["connector"] == "jira" for entry in jira_tools)


def test_tool_registry_owner_summary_separates_built_in_and_connector_tools():
    summary = get_tool_registry_owner_summary()

    assert summary["total"] == len(TOOL_REGISTRY_ENTRIES)
    assert summary["owner_counts"]["built_in"] > 0
    assert summary["owner_counts"]["connector"] > 0
    assert summary["connector_counts"]["jira"] > 0
    assert summary["connector_counts"]["aws"] > 0
