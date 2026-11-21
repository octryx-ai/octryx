"""Extended AWS, Azure and GCP cloud connector tool flows."""

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.tools_connectors_cloud_extended_support import AZURE_VM_ID, patch_cloud_connectors


def _cloud_context(project_config) -> ToolContext:
    return ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config=project_config,
    )


_AWS_PROJECT_CONFIG = {
    "aws_allowed_services": ["ec2", "logs", "rds", "lambda", "cloudtrail", "ce", "cloudwatch"],
    "tool_policy": {
        "allow_patterns": [
            "get_aws_*",
            "invoke_aws_*",
            "list_aws_*",
            "search_aws_*",
            "start_aws_*",
            "stop_aws_*",
        ],
        # High-risk tools need an exact-name grant; visibility patterns
        # never unlock them.
        "high_risk_grants": ["invoke_aws_lambda", "start_aws_ec2_instances", "stop_aws_ec2_instances"],
    },
}
_AZURE_PROJECT_CONFIG = {
    "azure_subscription_ids": ["sub-1"],
    "tool_policy": {
        "allow_patterns": ["get_azure_*", "list_azure_*", "start_azure_*", "stop_azure_*"],
        "high_risk_grants": ["start_azure_vm", "stop_azure_vm"],
    },
}
_GCP_PROJECT_CONFIG = {
    "gcp_project_id": "acme-orders-prod",
    "gcp_allowed_services": ["compute", "logging", "cloudsql", "monitoring", "cloudrun"],
}


async def _assert_aws_tools(aws_context) -> None:
    assert (await execute_tool("list_aws_ec2_instances", {}, aws_context))["instances"][0]["instance_id"] == "i-123"
    assert (await execute_tool("start_aws_ec2_instances", {"instance_ids": ["i-123"]}, aws_context))[
        "status"
    ] == "started"
    assert (await execute_tool("stop_aws_ec2_instances", {"instance_ids": ["i-123"]}, aws_context))[
        "status"
    ] == "stopped"
    assert (await execute_tool("get_aws_ec2_logs", {"log_group_name": "group"}, aws_context))["count"] == 1
    assert (await execute_tool("list_aws_rds_instances", {}, aws_context))["instances"][0]["identifier"] == "db-main"
    assert (await execute_tool("get_aws_rds_metrics", {"db_instance_identifier": "db-main"}, aws_context))["count"] == 1
    assert (
        await execute_tool(
            "get_aws_rds_slow_queries",
            {"db_instance_identifier": "db-main", "log_file_name": "postgresql.log"},
            aws_context,
        )
    )["count"] == 2
    assert (await execute_tool("list_aws_lambda_functions", {}, aws_context))["functions"][0][
        "name"
    ] == "acme-orders-handler"
    assert (await execute_tool("get_aws_lambda_logs", {"function_name": "acme-orders-handler"}, aws_context))[
        "count"
    ] == 1
    assert (
        await execute_tool(
            "invoke_aws_lambda", {"function_name": "acme-orders-handler", "payload": {"ping": True}}, aws_context
        )
    )["status_code"] == 200
    assert (await execute_tool("search_aws_cloudtrail_events", {}, aws_context))["events"][0]["event_id"] == "evt-1"
    assert (await execute_tool("get_aws_cost_by_service", {}, aws_context))["costs"][0]["service"] == "AmazonEC2"


async def _assert_azure_tools(azure_context) -> None:
    assert (await execute_tool("list_azure_vms", {}, azure_context))["virtual_machines"][0]["name"] == "vm-prod"
    assert (
        await execute_tool(
            "start_azure_vm",
            {"subscription_id": "sub-1", "resource_group": "rg-prod", "vm_name": "vm-prod"},
            azure_context,
        )
    )["status"] == "started"
    assert (
        await execute_tool(
            "stop_azure_vm",
            {"subscription_id": "sub-1", "resource_group": "rg-prod", "vm_name": "vm-prod"},
            azure_context,
        )
    )["status"] == "stopped"
    assert (await execute_tool("get_azure_monitor_alerts", {}, azure_context))["alerts"][0]["name"] == "cpu-alert"
    assert (await execute_tool("get_azure_monitor_metrics", {"resource_id": AZURE_VM_ID}, azure_context))["count"] == 1
    assert (await execute_tool("get_azure_cost", {"subscription_id": "sub-1"}, azure_context))["count"] == 1


async def _assert_gcp_tools(gcp_context) -> None:
    assert (await execute_tool("list_gcp_compute_instances", {}, gcp_context))["instances"][0]["name"] == "gce-1"
    assert (await execute_tool("get_gcp_compute_logs", {"instance_id": "1001"}, gcp_context))["count"] == 1
    assert (await execute_tool("list_gcp_cloud_sql_instances", {}, gcp_context))["instances"][0]["name"] == "sql-prod"
    assert (await execute_tool("get_gcp_cloud_sql_metrics", {"database_id": "sql-prod"}, gcp_context))["count"] == 1
    assert (await execute_tool("list_gcp_cloud_run_services", {}, gcp_context))["services"][0][
        "uri"
    ] == "https://api.run.app"
    assert (await execute_tool("get_gcp_cloud_run_logs", {"service_name": "api"}, gcp_context))["count"] == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_cloud_connector_tools_cover_extended_aws_azure_gcp_flows(monkeypatch):
    patch_cloud_connectors(monkeypatch)

    await _assert_aws_tools(_cloud_context(_AWS_PROJECT_CONFIG))
    await _assert_azure_tools(_cloud_context(_AZURE_PROJECT_CONFIG))
    await _assert_gcp_tools(_cloud_context(_GCP_PROJECT_CONFIG))
