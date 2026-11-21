"""Connector tools and health checks for the Docker registry, Harbor and Splunk."""

import pytest

from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_docker_registry_and_harbor_tools_cover_listing_vulnerabilities_and_tag_delete(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        if method == "GET" and url == "https://registry.example.com/v2/_catalog":
            return {"repositories": ["acme-orders/api"]}
        if method == "GET" and url == "https://registry.example.com/v2/acme-orders/api/tags/list":
            return {"name": "acme-orders/api", "tags": ["1.0.0", "1.0.1"]}
        if (
            method == "GET"
            and url
            == "https://registry.example.com/api/v2.0/projects/acme-orders/repositories/acme-orders%2Fapi/artifacts/1.0.1/additions/vulnerabilities"
        ):
            return [{"id": "CVE-2026-0001", "severity": "High"}]
        raise AssertionError(f"unexpected json call {method} {url}")

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, headers=None, params=None, json=None):
            request = httpx.Request(method, url)
            if method == "HEAD" and url == "https://registry.example.com/v2/acme-orders/api/manifests/1.0.1":
                return httpx.Response(200, headers={"Docker-Content-Digest": "sha256:abc123"}, request=request)
            if method == "DELETE" and url == "https://registry.example.com/v2/acme-orders/api/manifests/sha256:abc123":
                return httpx.Response(202, request=request)
            raise AssertionError(f"unexpected response call {method} {url}")

    import httpx

    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeAsyncClient())

    registry_context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["admin"],
        session_id="registry-session",
        project_config={
            "tool_policy": {"high_risk_grants": ["delete_tag"]},
            "docker_registry_provider": "registry",
            "docker_registry_url": "https://registry.example.com",
            "docker_registry_allowed_repositories": ["acme-orders/api"],
        },
    )
    harbor_context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["admin"],
        session_id="harbor-session",
        project_config={
            "docker_registry_provider": "harbor",
            "docker_registry_url": "https://registry.example.com",
            "docker_registry_allowed_repositories": ["acme-orders/api"],
            "harbor_project": "acme-orders",
        },
    )

    repos = await execute_tool("list_repositories", {}, registry_context)
    assert repos["count"] == 1
    tags = await execute_tool("list_tags", {"repository": "acme-orders/api"}, registry_context)
    assert tags["count"] == 2
    vulnerabilities = await execute_tool(
        "get_image_vulnerabilities",
        {"repository": "acme-orders/api", "reference": "1.0.1"},
        harbor_context,
    )
    assert vulnerabilities["count"] == 1
    deleted = await execute_tool("delete_tag", {"repository": "acme-orders/api", "tag": "1.0.1"}, registry_context)
    assert deleted["status"] == "deleted"
    assert deleted["digest"] == "sha256:abc123"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_docker_registry_connector_health_supports_registry_and_harbor(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, auth=None, params=None):
            request = httpx.Request("GET", url)
            if url.endswith("/v2/"):
                return httpx.Response(200, json={}, request=request)
            if url.endswith("/api/v2.0/systeminfo"):
                return httpx.Response(200, json={"harbor_version": "2.11.0"}, request=request)
            raise AssertionError(f"unexpected url {url}")

    import httpx

    monkeypatch.setattr("app.services.connector_test_service.httpx.AsyncClient", FakeAsyncClient)

    registry = await run_connector_connection_test(
        "docker_registry",
        {"docker_registry_provider": "registry", "docker_registry_url": "https://registry.example.com"},
    )
    assert registry["ok"] is True
    assert "Docker Registry" in registry["summary"]

    harbor = await run_connector_connection_test(
        "docker_registry",
        {
            "docker_registry_provider": "harbor",
            "docker_registry_url": "https://registry.example.com",
            "docker_registry_username": "robot",
            "docker_registry_password": "secret",
        },
    )
    assert harbor["ok"] is True
    assert "Harbor" in harbor["summary"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_splunk_tools_cover_search_saved_searches_alerts_and_index_stats(monkeypatch):
    async def fake_splunk_export_search(context, search, *, earliest_time=None, latest_time=None):
        if "stats count by index" in search:
            return [{"index": "acme_orders_prod", "count": "42"}]
        return [{"_time": "2026-03-28T08:00:00Z", "message": "error budget burn", "index": "acme_orders_prod"}]

    async def fake_splunk_json(context, method, path, *, params=None, form_data=None):
        assert method == "GET"
        assert path == "/servicesNS/-/-/saved/searches"
        return {
            "entry": [
                {
                    "name": "api-errors",
                    "content": {
                        "disabled": False,
                        "search": "search index=acme_orders_prod error",
                        "cron_schedule": "*/5 * * * *",
                        "alert_condition": "count > 0",
                    },
                }
            ]
        }

    monkeypatch.setattr("app.tools.connectors.splunk._splunk_export_search", fake_splunk_export_search)
    monkeypatch.setattr("app.tools.connectors.newrelic._splunk_export_search", fake_splunk_export_search)
    monkeypatch.setattr("app.tools.connectors.splunk._splunk_json", fake_splunk_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="splunk-session",
        project_config={
            "splunk_url": "https://splunk.example.com:8089",
            "splunk_token": "splunk-token",
            "splunk_allowed_indexes": ["acme_orders_prod"],
        },
    )

    search = await execute_tool("search_logs", {"query": "search index=acme_orders_prod error"}, context)
    assert search["count"] == 1

    searches = await execute_tool("get_saved_searches", {}, context)
    assert searches["count"] == 1
    assert searches["searches"][0]["name"] == "api-errors"

    alerts = await execute_tool("get_alerts", {"provider": "splunk"}, context)
    assert alerts["provider"] == "splunk"
    assert alerts["count"] == 1

    stats = await execute_tool("get_index_stats", {}, context)
    assert stats["count"] == 1
    assert stats["indexes"][0]["index"] == "acme_orders_prod"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_splunk_connector_health_supports_native_test(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, auth=None, params=None):
            request = httpx.Request("GET", url)
            if url.endswith("/services/server/info"):
                return httpx.Response(
                    200, json={"entry": [{"content": {"serverName": "splunk-prod"}}]}, request=request
                )
            raise AssertionError(f"unexpected url {url}")

    import httpx

    monkeypatch.setattr("app.services.connector_test_service.httpx.AsyncClient", FakeAsyncClient)

    result = await run_connector_connection_test(
        "splunk",
        {"splunk_url": "https://splunk.example.com:8089", "splunk_token": "splunk-token"},
    )
    assert result["ok"] is True
    assert "Splunk" in result["summary"]
