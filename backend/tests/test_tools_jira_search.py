"""Jira ticket search: JQL detection and project restriction, time windows, user work fields, fix versions and result limits."""

import pytest

from app.tools.context import ToolContext
from app.tools.jira_impl._jira_helpers_jql import (
    _inject_project_restriction,
    _looks_like_jql_query,
    _normalize_jql_shorthand,
)
from app.tools.jira_impl._jira_query_search import SearchJiraTickets


def test_jira_query_detection_and_shorthand_normalization():
    assert _looks_like_jql_query("updated >= -1d") is True
    assert _looks_like_jql_query('status = "In Progress" ORDER BY updated DESC') is True
    assert _looks_like_jql_query("find the latest payment ticket") is False
    assert _normalize_jql_shorthand("updated >= -1d") == "updated >= -24h"
    assert _normalize_jql_shorthand("created >= -7d ORDER BY updated DESC") == "created >= -168h ORDER BY updated DESC"


def test_inject_project_restriction_preserves_order_by_clause():
    assert (
        _inject_project_restriction(
            "updated >= -1d ORDER BY updated DESC",
            ["ACME"],
        )
        == 'project in ("ACME") AND (updated >= -24h) ORDER BY updated DESC'
    )


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_search_jira_tickets_treats_time_window_query_as_jql(monkeypatch):
    observed: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"issues": []}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            observed["url"] = url
            observed["params"] = params
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "jira_url": "https://jira.company.example",
            "jira_email": "ops@example.com",
            "jira_token": "secret",
            "jira_allowed_projects": ["ACME"],
        },
    )

    result = await SearchJiraTickets().execute({"query": "updated >= -1d", "limit": 50}, context)

    assert result["query"] == "updated >= -1d"
    assert result["jql"] == 'project in ("ACME") AND (updated >= -24h)'


@pytest.mark.asyncio
async def test_search_jira_tickets_returns_user_work_fields(monkeypatch):
    observed: dict[str, object] = {}

    async def fake_jira_api_get(client, jira_url, path, headers=None, params=None):
        observed["params"] = params
        return {
            "total": 1,
            "issues": [
                {
                    "key": "ACME-1",
                    "fields": {
                        "summary": "Investigate payment routing",
                        "status": {"name": "In Progress"},
                        "assignee": {"displayName": "Alice Example"},
                        "reporter": {"displayName": "Rina PM"},
                        "creator": {"displayName": "Alice Example"},
                        "priority": {"name": "High"},
                        "issuetype": {"name": "Task"},
                        "created": "2026-01-02T09:00:00.000+0100",
                        "updated": "2026-01-03T10:00:00.000+0100",
                    },
                }
            ],
        }, "2"

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_jira_api_get)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "jira_url": "https://jira.company.example",
            "jira_email": "ops@example.com",
            "jira_token": "secret",
            "jira_allowed_projects": ["ACME"],
        },
    )

    result = await SearchJiraTickets().execute(
        {"jql": '(assignee in ("alice") OR reporter in ("alice") OR creator in ("alice"))'},
        context,
    )

    # ``project`` is requested so the allowlist filter cross-checks every returned key.
    assert observed["params"]["fields"] == (
        "summary,status,assignee,reporter,creator,priority,issuetype,created,updated,project"
    )
    assert result["results"][0]["assignee"] == "Alice Example"
    assert result["results"][0]["reporter"] == "Rina PM"
    assert result["results"][0]["creator"] == "Alice Example"
    assert result["results"][0]["created"] == "2026-01-02T09:00:00.000+0100"


@pytest.mark.asyncio
async def test_search_jira_tickets_filters_by_fix_version(monkeypatch):
    observed: dict[str, object] = {}

    async def fake_jira_api_get(client, jira_url, path, headers=None, params=None):
        observed["params"] = params
        return {"total": 0, "issues": []}, "2"

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_jira_api_get)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "jira_url": "https://jira.company.example",
            "jira_email": "ops@example.com",
            "jira_token": "secret",
            "jira_allowed_projects": ["ACME"],
        },
    )

    result = await SearchJiraTickets().execute(
        {"project_key": "ACME", "fix_version": "shop_2.4.10", "limit": 100},
        context,
    )

    # Every query goes through the confined project restriction.
    assert observed["params"]["jql"] == (
        'project in ("ACME") AND (project = "ACME" AND fixVersion = "shop_2.4.10") ORDER BY updated DESC'
    )
    assert result["jql"] == observed["params"]["jql"]


@pytest.mark.asyncio
async def test_search_jira_tickets_caps_results_to_effective_limit(monkeypatch):
    observed: dict[str, object] = {}

    async def fake_jira_api_get(client, jira_url, path, headers=None, params=None):
        observed["params"] = params
        return {
            "total": 100,
            "issues": [
                {
                    "key": f"ACME-{idx}",
                    "fields": {
                        "summary": f"Issue {idx}",
                        "status": {"name": "Open"},
                        "issuetype": {"name": "Task"},
                    },
                }
                for idx in range(100)
            ],
        }, "2"

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_jira_api_get)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        turn_context_snapshot={"request_analysis": {"explicit_limit_requested": True, "explicit_limit_value": 1}},
        project_config={
            "jira_url": "https://jira.company.example",
            "jira_email": "ops@example.com",
            "jira_token": "secret",
            "jira_allowed_projects": ["ACME"],
        },
    )

    result = await SearchJiraTickets().execute({"jql": "project = ACME", "limit": 1}, context)

    assert observed["params"]["maxResults"] == 1
    assert result["max_results"] == 1
    assert len(result["results"]) == 1
    assert result["results"][0]["ticket_id"] == "ACME-0"


@pytest.mark.asyncio
async def test_search_jira_tickets_ignores_model_limit_without_user_limit(monkeypatch):
    observed: dict[str, object] = {}

    async def fake_jira_api_get(client, jira_url, path, headers=None, params=None):
        observed["params"] = params
        return {"issues": []}, "2"

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_jira_api_get)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        current_user_message="Erstelle eine Wochenzusammenfassung aus Jira, Bitbucket und Confluence.",
        project_config={
            "jira_url": "https://jira.company.example",
            "jira_email": "ops@example.com",
            "jira_token": "secret",
            "jira_allowed_projects": ["ACME"],
        },
    )

    await SearchJiraTickets().execute({"jql": "updated >= -7d ORDER BY updated DESC", "limit": 20}, context)
    assert observed["params"]["maxResults"] == 100
