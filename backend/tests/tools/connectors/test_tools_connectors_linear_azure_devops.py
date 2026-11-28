"""Connector tools and health checks for Linear and Azure DevOps."""

import pytest

from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_linear_tools_cover_issue_listing_create_and_update(monkeypatch):
    async def fake_linear_graphql(context, query, variables=None):
        if "LinearIssueTeam" in query:
            return {"issue": {"team": {"id": "team-acme-orders" if variables["id"] == "lin-2" else "team-other"}}}
        if "team(id: $teamId)" in query:
            return {
                "team": {
                    "id": variables["teamId"],
                    "name": "AcmeOrders",
                    "issues": {
                        "nodes": [
                            {
                                "id": "lin-1",
                                "identifier": "RIVER-101",
                                "title": "Investigate error budget",
                                "description": "Check API latency",
                                "priority": 2,
                                "state": {"id": "state-open", "name": "Todo"},
                                "assignee": {"id": "user-1", "name": "Alice"},
                            }
                        ]
                    },
                }
            }
        if "issueCreate" in query:
            return {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "lin-2",
                        "identifier": "RIVER-102",
                        "title": variables["input"]["title"],
                        "description": variables["input"].get("description"),
                        "priority": variables["input"].get("priority"),
                        "state": {"id": "state-open", "name": "Todo"},
                        "assignee": {"id": "user-1", "name": "Alice"},
                    },
                }
            }
        if "issueUpdate" in query:
            return {
                "issueUpdate": {
                    "success": True,
                    "issue": {
                        "id": variables["id"],
                        "identifier": "RIVER-102",
                        "title": variables["input"].get("title", "Updated issue"),
                        "description": variables["input"].get("description"),
                        "priority": variables["input"].get("priority"),
                        "state": {"id": variables["input"].get("stateId", "state-progress"), "name": "In Progress"},
                        "assignee": {"id": "user-2", "name": "Anna"},
                    },
                }
            }
        raise AssertionError("unexpected Linear query")

    monkeypatch.setattr("app.tools.connectors.issues._linear_graphql", fake_linear_graphql)
    monkeypatch.setattr("app.tools.connectors.linear._linear_graphql", fake_linear_graphql)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="linear-session",
        project_config={
            "tool_policy": {"high_risk_grants": ["create_issue", "update_issue"]},
            "linear_url": "https://api.linear.app/graphql",
            "linear_api_key": "linear-token",
            "linear_allowed_teams": ["team-acme-orders"],
            "linear_team_id": "team-acme-orders",
        },
    )

    issues = await execute_tool("list_issues", {"provider": "linear"}, context)
    assert issues["provider"] == "linear"
    assert issues["count"] == 1
    assert issues["issues"][0]["identifier"] == "RIVER-101"

    created = await execute_tool(
        "create_issue", {"title": "Prepare postmortem", "description": "Draft follow-up"}, context
    )
    assert created["provider"] == "linear"
    assert created["success"] is True
    assert created["issue"]["identifier"] == "RIVER-102"

    updated = await execute_tool(
        "update_issue",
        {"issue_id": "lin-2", "state_id": "state-progress", "title": "Prepare incident postmortem"},
        context,
    )
    assert updated["provider"] == "linear"
    assert updated["success"] is True
    assert updated["issue"]["state"] == "In Progress"
    # An issue of a team outside the allowlist is refused, even though the key could reach it.
    foreign = await execute_tool("update_issue", {"issue_id": "lin-9", "title": "x"}, context)
    assert foreign["error"] == "issue is not in an allowed team"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_linear_connector_health_supports_native_test(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            request = httpx.Request("POST", url)
            return httpx.Response(200, json={"data": {"viewer": {"id": "user-1", "name": "Alice"}}}, request=request)

    import httpx

    monkeypatch.setattr("app.services.connector_test_service.httpx.AsyncClient", FakeAsyncClient)

    result = await run_connector_connection_test(
        "linear",
        {"linear_url": "https://api.linear.app/graphql", "linear_api_key": "linear-token"},
    )
    assert result["ok"] is True
    assert "Linear" in result["summary"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_azure_devops_tools_cover_work_items_pipelines_and_logs(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        if method == "POST" and url == "https://dev.azure.com/acme-orders/AcmeOrders/_apis/wit/wiql":
            return {"workItems": [{"id": 17}]}
        if method == "GET" and url == "https://dev.azure.com/acme-orders/AcmeOrders/_apis/wit/workitems":
            return {
                "value": [
                    {
                        "id": 17,
                        "fields": {
                            "System.Title": "Investigate API errors",
                            "System.State": "Active",
                            "System.WorkItemType": "Issue",
                            "System.AssignedTo": {"displayName": "Alice"},
                        },
                    }
                ]
            }
        if method == "GET" and url == "https://dev.azure.com/acme-orders/AcmeOrders/_apis/pipelines":
            return {"value": [{"id": 9, "name": "Deploy API", "folder": "\\\\", "revision": 3}]}
        if method == "GET" and url == "https://dev.azure.com/acme-orders/AcmeOrders/_apis/pipelines/9/runs/44/logs":
            return {"value": [{"id": 1, "name": "build", "url": "https://logs.example.com/build"}]}
        raise AssertionError(f"unexpected request {method} {url}")

    async def fake_http_text(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert method == "GET"
        assert url == "https://logs.example.com/build"
        return "azure pipeline log output"

    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.ci_logs._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.ci_logs._http_text", fake_http_text)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="azure-devops-session",
        project_config={
            "azure_devops_url": "https://dev.azure.com/acme-orders",
            "azure_devops_pat": "azure-pat",
            "azure_devops_project": "AcmeOrders",
            "azure_devops_allowed_projects": ["AcmeOrders"],
        },
    )

    items = await execute_tool("list_work_items", {}, context)
    assert items["provider"] == "azure_devops"
    assert items["count"] == 1
    assert items["work_items"][0]["title"] == "Investigate API errors"

    pipelines = await execute_tool("list_pipelines", {}, context)
    assert pipelines["provider"] == "azure_devops"
    assert pipelines["count"] == 1
    assert pipelines["pipelines"][0]["name"] == "Deploy API"

    logs = await execute_tool(
        "get_pipeline_logs", {"provider": "azure_devops", "pipeline_id": 9, "run_id": 44}, context
    )
    assert logs["provider"] == "azure_devops"
    assert logs["job_logs"][0]["logs"] == "azure pipeline log output"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_azure_devops_connector_health_supports_native_test(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, auth=None, params=None):
            request = httpx.Request("GET", url)
            return httpx.Response(
                200, json={"count": 1, "value": [{"id": "proj-1", "name": "AcmeOrders"}]}, request=request
            )

    import httpx

    monkeypatch.setattr("app.services.connector_test_service.httpx.AsyncClient", FakeAsyncClient)

    result = await run_connector_connection_test(
        "azure_devops",
        {"azure_devops_url": "https://dev.azure.com/acme-orders", "azure_devops_pat": "azure-pat"},
    )
    assert result["ok"] is True
    assert "Azure DevOps" in result["summary"]
