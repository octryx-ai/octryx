"""Tests for connector tools: datadog observability, newrelic APM, ansible, connector health adapters, and cloud providers."""

import json

import pytest

from app.services import connector_test_service as connector_test_service_module
from app.services.connector_test_service import run_connector_connection_test
from app.tools.connectors import common as connector_common
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def _fake_datadog_json(url: str, headers: dict):
    assert headers["DD-API-KEY"] == "dd-api-key"
    assert headers["DD-APPLICATION-KEY"] == "dd-app-key"
    if url == "https://api.datadoghq.com/api/v1/query":
        return {
            "series": [
                {"metric": "system.cpu.user", "scope": ["host:web01"], "pointlist": [[1, 42.0], [2, 45.0]]}
            ]
        }
    if url == "https://api.datadoghq.com/api/v1/monitor":
        return [{"id": 11, "name": "High CPU", "type": "metric alert", "overall_state": "Alert"}]
    if url == "https://api.datadoghq.com/api/v1/events":
        return {
            "events": [{"id": 91, "title": "Deploy finished", "priority": "normal", "date_happened": 123456}]
        }
    if url == "https://api.datadoghq.com/api/v2/apm/events/search":
        return {
            "data": [
                {
                    "attributes": {
                        "attributes": {
                            "trace_id": "trace-1",
                            "service": "acme-orders-api",
                            "resource_name": "GET /health",
                            "duration": 12000000,
                        }
                    }
                }
            ]
        }
    if url == "https://api.datadoghq.com/api/v1/service_dependencies":
        return {
            "services": [{"name": "acme-orders-api"}, {"name": "postgres"}],
            "dependencies": [{"source": "acme-orders-api", "target": "postgres"}],
        }
    return None


def _fake_newrelic_json(url: str, headers: dict, json_body: dict | None):
    assert headers["Api-Key"] == "nr-api-key"
    if url == "https://api.newrelic.com/graphql":
        query = (json_body or {}).get("query") or ""
        if "nrql(query: $query)" in query:
            return {"data": {"actor": {"account": {"nrql": {"results": [{"count": 17}]}}}}}
        if "entitySearch" in query:
            return {
                "data": {
                    "actor": {
                        "entitySearch": {
                            "results": {
                                "entities": [
                                    {
                                        "guid": "NRGUID1",
                                        "name": "acme-orders-api",
                                        "type": "APPLICATION",
                                        "domain": "APM",
                                        "reporting": True,
                                        "alertSeverity": "CRITICAL",
                                    }
                                ]
                            }
                        },
                        "account": {"nrql": {"results": [{"avgDuration": 0.12, "errorRate": 1.5}]}},
                    }
                }
            }
    if url == "https://api.newrelic.com/v2/alerts_violations.json":
        return {
            "violations": [
                {
                    "id": 77,
                    "label": "High error rate",
                    "priority": "critical",
                    "state": "open",
                    "entity": {"name": "acme-orders-api"},
                }
            ]
        }
    return None


async def _fake_observability_http_json(
    method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None
):
    if "datadoghq" in url:
        payload = _fake_datadog_json(url, headers)
        if payload is not None:
            return payload
    if "newrelic" in url:
        payload = _fake_newrelic_json(url, headers, json_body)
        if payload is not None:
            return payload
    raise AssertionError(f"Unexpected request {method} {url}")


@pytest.mark.asyncio
async def test_datadog_and_newrelic_tools_cover_observability_and_apm_flows(monkeypatch):
    monkeypatch.setattr(connector_common, "_http_json", _fake_observability_http_json)

    datadog_context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "datadog_url": "https://api.datadoghq.com",
            "datadog_api_key": "dd-api-key",
            "datadog_app_key": "dd-app-key",
        },
    )
    newrelic_context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "newrelic_url": "https://api.newrelic.com",
            "newrelic_api_key": "nr-api-key",
            "newrelic_account_id": 1234567,
        },
    )

    metrics = await execute_tool("query_metrics", {"query": "avg:system.cpu.user{host:web01}"}, datadog_context)
    monitors = await execute_tool("list_monitors", {"query": "cpu"}, datadog_context)
    events = await execute_tool("get_events", {}, datadog_context)
    traces = await execute_tool("get_apm_traces", {"service": "acme-orders-api"}, datadog_context)
    service_map = await execute_tool("get_service_map", {}, datadog_context)
    nrql = await execute_tool("nrql_query", {"query": "SELECT count(*) FROM Transaction"}, newrelic_context)
    alerts = await execute_tool("get_alerts", {}, newrelic_context)
    apm = await execute_tool("get_apm_data", {"entity_name": "name = 'acme-orders-api'"}, newrelic_context)

    assert metrics["series"][0]["metric"] == "system.cpu.user"
    assert monitors["monitors"][0]["status"] == "Alert"
    assert events["events"][0]["title"] == "Deploy finished"
    assert traces["traces"][0]["trace_id"] == "trace-1"
    assert service_map["dependency_count"] == 1
    assert nrql["results"][0]["count"] == 17
    assert alerts["alerts"][0]["label"] == "High error rate"
    assert apm["entities"][0]["guid"] == "NRGUID1"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_connector_read_tools_ignore_model_limit_without_user_limit(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        if url == "https://api.datadoghq.com/api/v1/monitor":
            return [
                {"id": index, "name": f"Monitor {index}", "type": "metric alert", "overall_state": "OK"}
                for index in range(30)
            ]
        raise AssertionError(f"Unexpected request {method} {url}")

    monkeypatch.setattr(connector_common, "_http_json", fake_http_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        current_user_message="Erstelle eine Wochenzusammenfassung aus Jira, Bitbucket und Confluence.",
        project_config={
            "datadog_url": "https://api.datadoghq.com",
            "datadog_api_key": "dd-api-key",
            "datadog_app_key": "dd-app-key",
        },
    )

    result = await execute_tool("list_monitors", {"limit": 20, "query": "cpu"}, context)

    assert result["count"] == 30
    assert len(result["monitors"]) == 30


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_datadog_and_newrelic_connector_health_support_native_tests(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            if url == "https://api.datadoghq.com/api/v1/validate":
                assert headers["DD-API-KEY"] == "dd-api-key"
                assert headers["DD-APPLICATION-KEY"] == "dd-app-key"
                return FakeResponse({"valid": True})
            if url == "https://api.newrelic.com/v2/users.json":
                assert headers["Api-Key"] == "nr-api-key"
                return FakeResponse({"users": [{"email": "ops@example.com"}]})
            raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(connector_test_service_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    datadog = await run_connector_connection_test(
        "datadog",
        {
            "datadog_url": "https://api.datadoghq.com",
            "datadog_api_key": "dd-api-key",
            "datadog_app_key": "dd-app-key",
        },
    )
    newrelic = await run_connector_connection_test(
        "newrelic",
        {
            "newrelic_url": "https://api.newrelic.com",
            "newrelic_api_key": "nr-api-key",
            "newrelic_account_id": 1234567,
        },
    )

    assert datadog["ok"] is True
    assert datadog["summary"] == "Connected to Datadog."
    assert newrelic["ok"] is True
    assert newrelic["summary"] == "Connected to New Relic."
