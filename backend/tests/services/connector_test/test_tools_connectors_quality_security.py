"""SonarQube and Snyk quality and security tools and their native connector health tests."""

import pytest

from app.services import connector_test_service as connector_test_service_module
from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def _sonarqube_config() -> dict:
    return {
        "sonarqube_url": "https://sonarqube.example.com",
        "sonarqube_token": "sonar-token",
        "sonarqube_allowed_projects": ["acme-orders-api"],
    }


def _snyk_config() -> dict:
    return {
        "snyk_url": "https://api.snyk.io",
        "snyk_token": "snyk-token",
        "snyk_org_id": "org-123",
        "snyk_allowed_projects": ["acme-orders-api"],
    }


def _fake_sonarqube_json(url, headers):
    assert headers["Authorization"].startswith("Basic ")
    if url == "https://sonarqube.example.com/api/measures/component":
        return {
            "component": {
                "measures": [
                    {"metric": "bugs", "value": "3"},
                    {"metric": "coverage", "value": "82.1"},
                ]
            }
        }
    if url == "https://sonarqube.example.com/api/issues/search":
        return {
            "issues": [
                {
                    "key": "ISSUE-1",
                    "rule": "java:S1234",
                    "severity": "CRITICAL",
                    "type": "BUG",
                    "status": "OPEN",
                    "message": "Null pointer risk",
                    "component": "acme-orders-api:src/Main.java",
                    "line": 42,
                }
            ]
        }
    if url == "https://sonarqube.example.com/api/qualitygates/project_status":
        return {
            "projectStatus": {
                "status": "ERROR",
                "conditions": [{"metricKey": "coverage", "status": "ERROR"}],
                "ignoredConditions": False,
            }
        }
    return None


def _fake_snyk_json(url, headers):
    assert headers["Authorization"] == "token snyk-token"
    if url == "https://api.snyk.io/v1/org/org-123/project/acme-orders-api/issues":
        return {
            "issues": {
                "vulnerabilities": [
                    {
                        "id": "SNYK-1",
                        "title": "Prototype Pollution",
                        "severity": "high",
                        "packageName": "lodash",
                        "version": "4.17.19",
                        "identifiers": {"CVE": ["CVE-2020-8203"]},
                    }
                ]
            }
        }
    if url == "https://api.snyk.io/v1/org/org-123/project/acme-orders-api/issue/SNYK-1":
        return {
            "issue": {
                "id": "SNYK-1",
                "title": "Prototype Pollution",
                "severity": "high",
                "fixAdvice": ["Upgrade lodash to >=4.17.21"],
                "upgradePath": ["lodash@4.17.21"],
            }
        }
    return None


async def _fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
    if "sonarqube" in url:
        payload = _fake_sonarqube_json(url, headers)
        if payload is not None:
            return payload
    if "snyk" in url:
        payload = _fake_snyk_json(url, headers)
        if payload is not None:
            return payload
    raise AssertionError(f"unexpected call {method} {url}")


def _viewer_context(project_config: dict) -> ToolContext:
    return ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config=project_config,
    )


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_sonarqube_and_snyk_tools_cover_quality_and_security_flows(monkeypatch):
    monkeypatch.setattr("app.tools.connectors.common._http_json", _fake_http_json)

    sonar_context = _viewer_context(_sonarqube_config())
    snyk_context = _viewer_context(_snyk_config())

    metrics = await execute_tool("get_project_metrics", {"project_key": "acme-orders-api"}, sonar_context)
    assert metrics["metrics"]["bugs"] == "3"

    issues = await execute_tool("list_issues", {"project_key": "acme-orders-api"}, sonar_context)
    assert issues["count"] == 1
    assert issues["issues"][0]["severity"] == "CRITICAL"

    gate = await execute_tool("get_quality_gate", {"project_key": "acme-orders-api"}, sonar_context)
    assert gate["status"] == "ERROR"

    vulns = await execute_tool("list_vulnerabilities", {"project_id": "acme-orders-api"}, snyk_context)
    assert vulns["count"] == 1
    assert vulns["vulnerabilities"][0]["severity"] == "high"

    severity = await execute_tool("get_severity", {"project_id": "acme-orders-api", "issue_id": "SNYK-1"}, snyk_context)
    assert severity["severity"] == "high"

    advice = await execute_tool("get_fix_advice", {"project_id": "acme-orders-api", "issue_id": "SNYK-1"}, snyk_context)
    assert advice["fix_advice"] == ["Upgrade lodash to >=4.17.21"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_sonarqube_and_snyk_connector_health_support_native_tests(monkeypatch):
    class SonarResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"status": "UP"}

    class SnykResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"id": "org-123", "name": "Acme Orders Org"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, auth=None, headers=None):
            if url == "https://sonarqube.example.com/api/system/status":
                assert auth is not None
                return SonarResponse()
            if url == "https://api.snyk.io/v1/org/org-123":
                assert headers["Authorization"] == "token snyk-token"
                return SnykResponse()
            raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(connector_test_service_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    sonar = await run_connector_connection_test(
        "sonarqube",
        {
            "sonarqube_url": "https://sonarqube.example.com",
            "sonarqube_token": "sonar-token",
            "sonarqube_allowed_projects": ["acme-orders-api"],
        },
    )
    snyk = await run_connector_connection_test(
        "snyk",
        {
            "snyk_url": "https://api.snyk.io",
            "snyk_token": "snyk-token",
            "snyk_org_id": "org-123",
            "snyk_allowed_projects": ["acme-orders-api"],
        },
    )

    assert sonar["ok"] is True
    assert sonar["summary"] == "Connected to SonarQube."
    assert snyk["ok"] is True
    assert snyk["summary"] == "Connected to Snyk."
