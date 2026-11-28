"""Creating Jira sprints and sprint bundles, including the retry without an issue type."""

from typing import Any

import pytest

from app.tools.context import ToolContext
from app.tools.jira_impl._jira_board_tools import ListJiraBoards
from app.tools.jira_impl._jira_release_bundle import CreateJiraReleaseBundle
from app.tools.jira_impl._jira_sprint_tools import CreateJiraSprint, CreateJiraSprintBundle


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_create_jira_sprint_creates_or_updates_future_sprint(monkeypatch):
    observed_posts: list[tuple[str, dict[str, Any]]] = []
    observed_puts: list[tuple[str, dict[str, Any]]] = []

    async def fake_agile_get(client, jira_url, path, *, headers=None, params=None):
        assert path == "/board/17/sprint"
        return {
            "values": [
                {
                    "id": 901,
                    "name": "Acme Orders Stabilization Sprint",
                    "state": "future",
                    "goal": "old",
                }
            ]
        }

    async def fake_agile_post(client, jira_url, path, *, headers=None, payload=None):
        observed_posts.append((path, payload or {}))
        return {"id": 902, "name": payload["name"], "state": "future", "goal": payload.get("goal")}, 201

    async def fake_agile_put(client, jira_url, path, *, headers=None, payload=None):
        observed_puts.append((path, payload or {}))
        return {
            "id": 901,
            "name": payload["name"],
            "state": "future",
            "goal": payload.get("goal"),
            "startDate": payload.get("startDate"),
            "endDate": payload.get("endDate"),
        }, 200

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_agile_get", fake_agile_get)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_agile_post", fake_agile_post)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_agile_put", fake_agile_put)

    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={
            "jira_url": "https://jira.example.com/jira",
            "jira_username": "alice",
            "jira_password": "secret",
            "jira_allowed_projects": ["ACME"],
        },
        capability_type="change",
        agent_mode_key="change",
        workspace_root="/tmp",
    )

    result = await CreateJiraSprint().execute(
        {
            "board_id": 17,
            "name": "Acme Orders Stabilization Sprint",
            "start_date": "2026-04-14",
            "end_date": "2026-04-28",
            "goal": "Stabilize AWS environment operations and release readiness.",
        },
        context,
    )

    assert result["sprint_id"] == 901
    assert result["created"] is False
    assert result["status"] == "updated"
    assert observed_posts == []
    assert observed_puts[0][0] == "/sprint/901"
    assert observed_puts[0][1]["goal"] == "Stabilize AWS environment operations and release readiness."
    assert observed_puts[0][1]["startDate"].startswith("2026-04-14T09:00:00.000")
    assert observed_puts[0][1]["endDate"].startswith("2026-04-28T17:00:00.000")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_create_jira_sprint_bundle_uses_release_and_sprint_tools(monkeypatch):
    async def fake_list_boards(self, params, context):
        return {"boards": [{"id": 3572, "name": "ACME Sprint Board", "type": "scrum"}]}

    async def fake_release_bundle(self, params, context):
        return {
            "release_name": "ai-enterprise-sprint",
            "release_date": "2026-04-28",
            "version_id": "2001",
            "release_status": "prepared",
            "created_tickets": [
                {
                    "ticket_id": "ACME-501",
                    "priority": "Highest",
                    "assignee": "alice",
                    "references": ["https://confluence.example/wiki/x/OPS"],
                },
                {"ticket_id": "ACME-502"},
            ],
            "created_ticket_count": 2,
            "updated_tickets": [],
            "updated_ticket_count": 0,
        }

    async def fake_create_sprint(self, params, context):
        assert params["board_id"] == "3572"
        return {
            "board_id": "3572",
            "sprint_id": 991,
            "name": params["name"],
            "state": "future",
            "goal": params.get("goal"),
        }

    async def fake_add_to_sprint(self, params, context):
        return {"status": "added_to_sprint", "sprint_id": params["sprint_id"], "ticket_ids": params["ticket_ids"]}

    monkeypatch.setattr(ListJiraBoards, "execute", fake_list_boards)
    monkeypatch.setattr(CreateJiraReleaseBundle, "execute", fake_release_bundle)
    monkeypatch.setattr(CreateJiraSprint, "execute", fake_create_sprint)
    monkeypatch.setattr("app.tools.jira_impl._jira_sprint_issue_tools.AddIssuesToSprint.execute", fake_add_to_sprint)

    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={
            "jira_url": "https://jira.example.com/jira",
            "jira_username": "alice",
            "jira_password": "secret",
            "jira_allowed_projects": ["ACME"],
        },
        capability_type="change",
        agent_mode_key="change",
        workspace_root="/tmp",
    )

    result = await CreateJiraSprintBundle().execute(
        {
            "release_name": "ai-enterprise-sprint",
            "sprint_name": "AI Enterprise Sprint",
            "sprint_goal": "Stabilize Acme Orders AWS operations.",
            "tickets": [
                {
                    "summary": "One",
                    "priority": "Highest",
                    "assignee": "alice",
                    "description": "Use https://confluence.example/wiki/x/OPS and https://bitbucket.example/projects/OCX/repos/acme-orders for context.",
                },
                {"summary": "Two"},
            ],
        },
        context,
    )

    assert result["version_id"] == "2001"
    assert result["sprint_id"] == 991
    assert result["assigned_to_sprint"] == ["ACME-501", "ACME-502"]
    assert result["status"] == "created"
    assert result["created_tickets"][0]["priority"] == "Highest"
    assert result["created_tickets"][0]["assignee"] == "alice"
    assert "https://confluence.example/wiki/x/OPS" in result["created_tickets"][0]["references"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_create_jira_sprint_bundle_retries_without_issue_type_on_400(monkeypatch):
    release_calls: list[dict[str, Any]] = []

    async def fake_list_boards(self, params, context):
        return {"boards": [{"id": 3572, "name": "ACME Sprint Board", "type": "scrum"}]}

    async def fake_release_bundle(self, params, context):
        release_calls.append(dict(params))
        if len(release_calls) == 1:
            return {
                "error": "Tool execution failed: Client error '400 ' for url 'https://jira.example.com/rest/api/2/issue'"
            }
        assert params.get("issue_type") == ""
        assert all(not str((ticket or {}).get("issue_type") or "").strip() for ticket in (params.get("tickets") or []))
        return {
            "release_name": "ai-enterprise-sprint",
            "release_date": "2026-04-28",
            "version_id": "2001",
            "release_status": "prepared",
            "created_tickets": [{"ticket_id": "ACME-501"}],
            "created_ticket_count": 1,
            "updated_tickets": [],
            "updated_ticket_count": 0,
        }

    async def fake_create_sprint(self, params, context):
        return {
            "board_id": "3572",
            "sprint_id": 991,
            "name": params["name"],
            "state": "future",
            "goal": params.get("goal"),
        }

    async def fake_add_to_sprint(self, params, context):
        return {"status": "added_to_sprint", "sprint_id": params["sprint_id"], "ticket_ids": params["ticket_ids"]}

    monkeypatch.setattr(ListJiraBoards, "execute", fake_list_boards)
    monkeypatch.setattr(CreateJiraReleaseBundle, "execute", fake_release_bundle)
    monkeypatch.setattr(CreateJiraSprint, "execute", fake_create_sprint)
    monkeypatch.setattr("app.tools.jira_impl._jira_sprint_issue_tools.AddIssuesToSprint.execute", fake_add_to_sprint)

    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={
            "jira_url": "https://jira.example.com/jira",
            "jira_username": "alice",
            "jira_password": "secret",
            "jira_allowed_projects": ["ACME"],
        },
        capability_type="change",
        agent_mode_key="change",
        workspace_root="/tmp",
    )

    result = await CreateJiraSprintBundle().execute(
        {
            "release_name": "ai-enterprise-sprint",
            "sprint_name": "AI Enterprise Sprint",
            "issue_type": "Task",
            "tickets": [{"summary": "One", "issue_type": "Task"}],
        },
        context,
    )

    assert len(release_calls) == 2
    assert result["status"] == "created"
    assert result["assigned_to_sprint"] == ["ACME-501"]
