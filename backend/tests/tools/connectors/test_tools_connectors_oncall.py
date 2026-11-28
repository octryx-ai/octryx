"""PagerDuty and Opsgenie incident connector tools for the on-call flow, and their shared connection test."""

import pytest

from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def _incident_tool_policy() -> dict:
    return {
        "allowlist": [
            "acknowledge",
            "create_incident",
            "escalate",
            "get_escalation_policy",
            "get_schedule",
            "list_oncall",
            "resolve",
        ]
    }


def _incident_context(project_config: dict) -> ToolContext:
    return ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={**project_config, "tool_policy": _incident_tool_policy()},
    )


async def _fake_pagerduty_http_json(
    method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None
):
    assert headers["Authorization"] == "Token token=pd-token"
    if method == "POST" and url == "https://api.pagerduty.com/incidents":
        assert json_body["incident"]["service"]["id"] == "P12345"
        return {
            "incident": {
                "id": "PI1",
                "incident_number": 77,
                "title": json_body["incident"]["title"],
                "status": "triggered",
                "urgency": json_body["incident"]["urgency"],
                "service": {"id": "P12345", "summary": "Acme Orders API"},
                "escalation_policy": {"id": "EP12345", "summary": "Primary EP"},
                "assignments": [{"assignee": {"id": "U1", "summary": "Primary Oncall"}}],
            }
        }
    if method == "POST" and url == "https://api.pagerduty.com/incidents/PI1/responder_requests":
        return {"status": "success", "message": "escalated"}
    if method == "GET" and url == "https://api.pagerduty.com/oncalls":
        assert params["schedule_ids[]"] == ["S12345"]
        return {
            "oncalls": [
                {
                    "id": "OC1",
                    "summary": "Primary Oncall",
                    "user": {"id": "U1", "summary": "Primary Oncall"},
                    "schedule": {"summary": "Prod Schedule"},
                    "escalation_level": 1,
                }
            ]
        }
    if method == "PUT" and url == "https://api.pagerduty.com/incidents/PI1":
        return {
            "incident": {
                "id": "PI1",
                "title": "DB latency spike",
                "status": json_body["incident"]["status"],
                "service": {"summary": "Acme Orders API"},
                "assignments": [],
            }
        }
    if method == "GET" and url == "https://api.pagerduty.com/schedules/S12345":
        return {"schedule": {"id": "S12345", "name": "Prod Schedule", "time_zone": "UTC"}}
    if method == "GET" and url == "https://api.pagerduty.com/escalation_policies/EP12345":
        return {
            "escalation_policy": {
                "id": "EP12345",
                "name": "Primary EP",
                "num_loops": 2,
                "services": [{"id": "P12345", "summary": "Acme Orders API"}],
            }
        }
    raise AssertionError(f"unexpected call {method} {url}")


async def _fake_opsgenie_http_json(
    method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None
):
    assert headers["Authorization"] == "GenieKey og-token"
    if method == "POST" and url == "https://api.opsgenie.com/v2/alerts":
        return {"requestId": "REQ1", "data": {"alertId": "AL1", "message": json_body["message"], "status": "open"}}
    if method == "POST" and url == "https://api.opsgenie.com/v2/alerts/AL1/escalate":
        return {"requestId": "REQ2", "data": {"alertId": "AL1", "status": "escalated"}}
    if method == "GET" and url == "https://api.opsgenie.com/v2/schedules/schedule-prod/on-calls":
        return {"data": {"onCallParticipants": [{"id": "team-prod", "name": "Prod Team", "type": "team"}]}}
    if method == "POST" and url == "https://api.opsgenie.com/v2/alerts/AL1/acknowledge":
        return {"requestId": "REQ3", "data": {"alertId": "AL1", "status": "acknowledged"}}
    if method == "POST" and url == "https://api.opsgenie.com/v2/alerts/AL1/close":
        return {"requestId": "REQ4", "data": {"alertId": "AL1", "status": "closed"}}
    if method == "GET" and url == "https://api.opsgenie.com/v2/schedules/schedule-prod":
        return {"data": {"id": "schedule-prod", "name": "Prod Schedule", "timezone": "Europe/Zurich"}}
    if method == "GET" and url == "https://api.opsgenie.com/v2/escalations/escalation-prod":
        return {"data": {"id": "escalation-prod", "name": "Primary Escalation"}}
    raise AssertionError(f"unexpected call {method} {url}")


@pytest.mark.asyncio
async def test_pagerduty_incident_tools_cover_core_oncall_flow(monkeypatch):
    monkeypatch.setattr("app.tools.connectors.common._http_json", _fake_pagerduty_http_json)

    context = _incident_context(
        {
            "incident_provider": "pagerduty",
            "pagerduty_token": "pd-token",
            "pagerduty_service_ids": ["P12345"],
            "pagerduty_schedule_ids": ["S12345"],
            "pagerduty_escalation_policy_ids": ["EP12345"],
        }
    )

    created = await execute_tool(
        "create_incident",
        {"title": "DB latency spike", "details": "latency above threshold", "assignee_ids": ["U1"]},
        context,
    )
    assert created["provider"] == "pagerduty"
    assert created["incident"]["id"] == "PI1"

    oncall = await execute_tool("list_oncall", {}, context)
    assert oncall["count"] == 1
    assert oncall["oncalls"][0]["user"] == "Primary Oncall"

    escalated = await execute_tool("escalate", {"incident_id": "PI1", "responder_ids": ["U2"]}, context)
    assert escalated["status"] == "escalated"

    acknowledged = await execute_tool("acknowledge", {"incident_id": "PI1"}, context)
    assert acknowledged["incident"]["status"] == "acknowledged"

    resolved = await execute_tool("resolve", {"incident_id": "PI1"}, context)
    assert resolved["incident"]["status"] == "resolved"

    schedule = await execute_tool("get_schedule", {}, context)
    assert schedule["schedule"]["id"] == "S12345"

    policy = await execute_tool("get_escalation_policy", {}, context)
    assert policy["policy"]["id"] == "EP12345"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_opsgenie_incident_tools_cover_core_oncall_flow(monkeypatch):
    monkeypatch.setattr("app.tools.connectors.common._http_json", _fake_opsgenie_http_json)

    context = _incident_context(
        {
            "incident_provider": "opsgenie",
            "opsgenie_token": "og-token",
            "opsgenie_schedule_ids": ["schedule-prod"],
            "opsgenie_team_ids": ["team-prod"],
            "opsgenie_escalation_ids": ["escalation-prod"],
        }
    )

    created = await execute_tool("create_incident", {"title": "Pod crashloop"}, context)
    assert created["provider"] == "opsgenie"
    assert created["incident"]["id"] == "AL1"

    oncall = await execute_tool("list_oncall", {}, context)
    assert oncall["oncalls"][0]["name"] == "Prod Team"

    escalated = await execute_tool("escalate", {"incident_id": "AL1"}, context)
    assert escalated["provider"] == "opsgenie"

    acknowledged = await execute_tool("acknowledge", {"incident_id": "AL1"}, context)
    assert acknowledged["incident"]["request_id"] == "AL1"

    resolved = await execute_tool("resolve", {"incident_id": "AL1"}, context)
    assert resolved["incident"]["request_id"] == "AL1"

    schedule = await execute_tool("get_schedule", {}, context)
    assert schedule["schedule"]["id"] == "schedule-prod"

    policy = await execute_tool("get_escalation_policy", {}, context)
    assert policy["policy"]["id"] == "escalation-prod"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_pagerduty_connector_health_supports_pagerduty_and_opsgenie(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, auth=None, params=None):
            request = httpx.Request("GET", url)
            if url.endswith("/users/me"):
                return httpx.Response(200, json={"user": {"summary": "PD User"}}, request=request)
            if url.endswith("/v2/account"):
                return httpx.Response(200, json={"data": {"name": "Ops Team"}}, request=request)
            raise AssertionError(f"unexpected url {url}")

    import httpx

    monkeypatch.setattr("app.services.connector_test_service.httpx.AsyncClient", FakeAsyncClient)

    pagerduty = await run_connector_connection_test(
        "pagerduty",
        {"incident_provider": "pagerduty", "pagerduty_url": "https://api.pagerduty.com", "pagerduty_token": "pd-token"},
    )
    assert pagerduty["ok"] is True
    assert "PagerDuty" in pagerduty["summary"]

    opsgenie = await run_connector_connection_test(
        "pagerduty",
        {"incident_provider": "opsgenie", "opsgenie_url": "https://api.opsgenie.com", "opsgenie_token": "og-token"},
    )
    assert opsgenie["ok"] is True
    assert "OpsGenie" in opsgenie["summary"]
