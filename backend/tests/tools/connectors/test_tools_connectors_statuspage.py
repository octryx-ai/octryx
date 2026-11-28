"""Statuspage connector tools for incidents and component updates, and its native connection test."""

import pytest

from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_statuspage_tools_cover_incidents_and_component_updates(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert headers["Authorization"] == "OAuth sp-token"
        if method == "GET" and url == "https://api.statuspage.io/v1/pages/page-123/components":
            return [
                {"id": "component-api", "name": "API", "status": "operational"},
                {"id": "component-db", "name": "Database", "status": "partial_outage"},
            ]
        raise AssertionError(f"unexpected json call {method} {url}")

    async def fake_http_form_json(method, url, *, headers=None, params=None, form_data=None, timeout=30, connection=None):
        assert headers["Authorization"] == "OAuth sp-token"
        if method == "POST" and url == "https://api.statuspage.io/v1/pages/page-123/incidents":
            assert form_data["incident[name]"] == "API latency"
            assert form_data["incident[status]"] == "investigating"
            assert form_data["incident[component_ids][]"] == ["component-api"]
            return {
                "id": "inc-1",
                "name": "API latency",
                "status": "investigating",
                "impact": "minor",
            }
        if method == "PATCH" and url == "https://api.statuspage.io/v1/pages/page-123/incidents/inc-1":
            return {
                "id": "inc-1",
                "name": form_data.get("incident[name]", "API latency"),
                "status": form_data.get("incident[status]", "investigating"),
            }
        if method == "PATCH" and url == "https://api.statuspage.io/v1/pages/page-123/components/component-api":
            assert form_data["component[status]"] == "degraded_performance"
            return {
                "id": "component-api",
                "name": "API",
                "status": "degraded_performance",
            }
        raise AssertionError(f"unexpected form call {method} {url}")

    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.common._http_form_json", fake_http_form_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "incident_provider": "statuspage",
            "statuspage_api_key": "sp-token",
            "statuspage_page_id": "page-123",
            "statuspage_allowed_page_ids": ["page-123"],
            "statuspage_allowed_component_ids": ["component-api", "component-db"],
            "tool_policy": {
                "allowlist": [
                    "create_incident",
                    "list_components",
                    "resolve_incident",
                    "update_component_status",
                    "update_incident",
                ]
            },
        },
    )

    created = await execute_tool(
        "create_incident",
        {"title": "API latency", "details": "latency above threshold", "component_ids": ["component-api"]},
        context,
    )
    assert created["provider"] == "statuspage"
    assert created["incident"]["id"] == "inc-1"

    updated = await execute_tool("update_incident", {"incident_id": "inc-1", "status": "identified"}, context)
    assert updated["incident"]["status"] == "identified"

    resolved = await execute_tool("resolve_incident", {"incident_id": "inc-1"}, context)
    assert resolved["status"] == "resolved"
    assert resolved["incident"]["status"] == "resolved"

    components = await execute_tool("list_components", {}, context)
    assert components["count"] == 2
    assert components["components"][0]["id"] == "component-api"

    component = await execute_tool(
        "update_component_status",
        {"component_id": "component-api", "status": "degraded_performance"},
        context,
    )
    assert component["component"]["status"] == "degraded_performance"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_statuspage_connector_health_supports_native_test(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, auth=None, params=None):
            request = httpx.Request("GET", url)
            if url.endswith("/v1/pages/page-123"):
                return httpx.Response(200, json={"id": "page-123", "name": "Acme Orders Status"}, request=request)
            raise AssertionError(f"unexpected url {url}")

    import httpx

    monkeypatch.setattr("app.services.connector_test_service.httpx.AsyncClient", FakeAsyncClient)

    statuspage = await run_connector_connection_test(
        "statuspage",
        {
            "statuspage_url": "https://api.statuspage.io",
            "statuspage_api_key": "sp-token",
            "statuspage_page_id": "page-123",
        },
    )
    assert statuspage["ok"] is True
    assert "Statuspage" in statuspage["summary"]
