"""Tool definitions and executing unknown tools or tools without config."""

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool, get_tool_definitions


def test_tool_definitions():
    defs = get_tool_definitions("diagnosis")
    assert len(defs) >= 93
    names = [d["function"]["name"] for d in defs]
    assert "read_grafana_alert" in names
    assert "render_panel_as_image" in names
    assert "create_snapshot" in names
    assert "get_dashboard_json" in names
    assert "query_prometheus" in names
    assert "search_jira_tickets" in names
    assert "get_jira_ticket" in names
    assert "list_jira_transitions" in names
    assert "transition_jira_ticket" in names
    assert "add_jira_comment" in names
    assert "get_system_context" in names
    assert "get_current_time" in names
    assert "list_bitbucket_repositories" in names
    assert "list_bitbucket_directory" in names
    assert "list_bitbucket_commits" in names
    assert "list_recent_bitbucket_commits" in names
    assert "get_bitbucket_commit_changes" in names
    assert "get_confluence_page" in names
    assert "http_request" not in names
    assert "list_workspace_directory" in names
    assert "read_workspace_file" in names
    assert "analyze_workspace_repository" in names
    assert "list_repository_readme_status" in names
    assert "list_workspace_git_commits" in names
    assert "run_kubectl" in names
    assert "run_saved_python_script" in names
    assert "list_github_repositories" in names
    assert "list_github_pull_requests" in names
    assert "list_github_action_runs" in names
    assert "get_job_logs" in names
    assert "get_pipeline_logs" in names
    assert "trigger_workflow" in names
    assert "retry_job" in names
    assert "cancel_pipeline" in names
    assert "list_artifacts" in names
    assert "get_artifact" in names
    assert "get_test_results" in names
    assert "read_secret" in names
    assert "list_secrets" in names
    assert "renew_lease" in names
    assert "revoke_token" in names
    assert "audit_log_read" in names
    assert "get_project_metrics" in names
    assert "list_issues" in names
    assert "get_quality_gate" in names

    change_names = {d["function"]["name"] for d in get_tool_definitions("change")}
    assert "http_request" in change_names
    assert "list_vulnerabilities" in names
    assert "get_severity" in names
    assert "get_fix_advice" in names
    assert "list_gitlab_projects" in names
    assert "list_gitlab_merge_requests" in names
    assert "list_gitlab_pipelines" in names
    assert "search_notion_pages" in names
    assert "get_notion_page" in names
    assert "search_sharepoint" in names
    assert "list_sharepoint_site_pages" in names
    assert "list_servicenow_records" in names
    assert "get_servicenow_record" in names
    assert "list_servicenow_incidents" in names
    assert "list_servicenow_changes" in names
    assert "get_elasticsearch_cluster_health" in names
    assert "search_elasticsearch_documents" in names
    assert "list_aws_eks_clusters" in names
    assert "list_aws_cloudwatch_alarms" in names
    assert "list_azure_resource_groups" in names
    assert "list_azure_aks_clusters" in names
    assert "list_gcp_projects" in names
    assert "list_gcp_gke_clusters" in names


@pytest.mark.asyncio
async def test_execute_unknown_tool():
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
    )
    result = await execute_tool("nonexistent", {}, context)
    assert "error" in result
    assert result["policy"] == "tool_governance_metadata"
    assert result["policy_decision"]["reason"] == "unknown_tool_requires_metadata"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_execute_tool_no_config():
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
    )
    result = await execute_tool("read_grafana_alert", {"alert_id": "test"}, context)
    assert "error" in result
