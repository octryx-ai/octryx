"""Native AWS, Azure and GCP listing tools, cloud connector health and ServiceNow incidents."""

import pytest

from app.services import connector_test_service as connector_test_service_module
from app.services.connector_test_service import run_connector_connection_test
from app.tools.connectors import aws_core, gcp_core
from app.tools.connectors import azure as azure_connector
from app.tools.connectors import common as connector_common
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_aws_eks_clusters_tool_uses_native_helper(monkeypatch):
    async def fake_aws_json(context, service, command):
        assert service == "eks"
        assert command == ["list-clusters"]
        return {"clusters": ["acme-orders-prod", "acme-orders-nonprod"]}

    monkeypatch.setattr("app.tools.connectors.aws_compute._aws_json", fake_aws_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={"aws_allowed_services": ["eks"]},
    )
    result = await execute_tool("list_aws_eks_clusters", {}, context)
    assert result["count"] == 2
    assert "acme-orders-prod" in result["clusters"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_azure_resource_groups_tool(monkeypatch):
    async def fake_token(context):
        return "azure-token"

    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert method == "GET"
        assert headers["Authorization"] == "Bearer azure-token"
        return {
            "value": [
                {
                    "name": "rg-acme-orders",
                    "location": "westeurope",
                    "id": "/subscriptions/sub-1/resourceGroups/rg-acme-orders",
                }
            ]
        }

    monkeypatch.setattr("app.tools.connectors.azure._azure_token", fake_token)
    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={"azure_subscription_ids": ["sub-1"]},
    )
    result = await execute_tool("list_azure_resource_groups", {}, context)
    assert result["count"] == 1
    assert result["resource_groups"][0]["name"] == "rg-acme-orders"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_gcp_projects_tool_accepts_configured_access_token(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert method == "GET"
        assert headers["Authorization"] == "Bearer gcp-token"
        return {
            "projects": [
                {
                    "projectId": "acme-orders-prod",
                    "name": "Acme Orders Production",
                    "projectNumber": "123",
                    "lifecycleState": "ACTIVE",
                }
            ]
        }

    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={"gcp_access_token": "gcp-token"},
    )
    result = await execute_tool("list_gcp_projects", {}, context)
    assert result["count"] == 1
    assert result["projects"][0]["project_id"] == "acme-orders-prod"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_cloud_connector_health_supports_aws_azure_and_gcp(monkeypatch):
    async def fake_aws_json(context, service, command):
        assert service == "sts"
        assert command == ["get-caller-identity"]
        return {"Arn": "arn:aws:sts::123456789012:assumed-role/Octryx/test"}

    async def fake_azure_token(context):
        return "azure-token"

    async def fake_gcp_access_token(context):
        return "gcp-token"

    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        if "management.azure.com" in url:
            return {"value": [{"name": "rg-prod"}]}
        if "cloudresourcemanager.googleapis.com" in url:
            return {"projects": [{"projectId": "acme-orders-prod"}]}
        raise AssertionError(f"Unexpected HTTP call {method} {url}")

    monkeypatch.setattr(
        connector_test_service_module.shutil, "which", lambda command: "/usr/bin/aws" if command == "aws" else None
    )
    monkeypatch.setattr(aws_core, "_aws_json", fake_aws_json)
    monkeypatch.setattr(azure_connector, "_azure_token", fake_azure_token)
    monkeypatch.setattr(gcp_core, "_gcp_access_token", fake_gcp_access_token)
    monkeypatch.setattr(connector_common, "_http_json", fake_http_json)

    aws = await run_connector_connection_test("aws", {"aws_allowed_services": ["sts"]})
    azure = await run_connector_connection_test("azure", {"azure_subscription_ids": ["sub-1"]})
    gcp = await run_connector_connection_test(
        "gcp", {"gcp_project_id": "acme-orders-prod", "gcp_access_token": "gcp-token"}
    )

    assert aws["ok"] is True
    assert aws["summary"] == "Connected to AWS."
    assert azure["ok"] is True
    assert azure["summary"] == "Connected to Azure."
    assert gcp["ok"] is True
    assert gcp["summary"] == "Connected to GCP."


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_servicenow_incidents_uses_token_and_allowed_table(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert method == "GET"
        assert url == "https://company.service-now.com/api/now/table/incident"
        assert headers["Authorization"] == "Bearer sn-token"
        assert params["sysparm_limit"] == 5
        return {
            "result": [
                {
                    "sys_id": "abc123",
                    "number": "INC0012345",
                    "short_description": "Payment processing degraded",
                    "state": "2",
                    "priority": "2",
                    "assignment_group": "Acme Orders OPS",
                    "assigned_to": "Alice Example",
                    "sys_updated_on": "2026-03-25 12:00:00",
                }
            ]
        }

    monkeypatch.setattr("app.tools.connectors.servicenow._http_json", fake_http_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "servicenow_url": "https://company.service-now.com",
            "servicenow_auth_mode": "bearer_token",
            "servicenow_token": "sn-token",
            "servicenow_allowed_tables": ["incident", "change_request"],
        },
    )
    result = await execute_tool("list_servicenow_incidents", {"limit": 5}, context)
    assert result["count"] == 1
    assert result["incidents"][0]["number"] == "INC0012345"
