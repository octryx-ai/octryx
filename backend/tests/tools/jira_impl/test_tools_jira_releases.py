"""Jira write approvals and release bundles: change previews for ticket updates and creating or updating release versions."""

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.models import ChangePreview, Session
from app.tools.context import ToolContext
from app.tools.jira_impl._jira_release_bundle import CreateJiraReleaseBundle
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_update_jira_ticket_in_diagnosis_requires_approval_with_change_preview(db, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={
            "jira_url": "https://jira.example.com",
            "jira_allowed_projects": ["RIVER"],
            "tool_policy": {"allowlist": ["update_jira_ticket"]},
        },
        capability_type="diagnosis",
        agent_mode_key="diagnosis",
        workspace_root="/tmp",
        db=db,
    )

    result = await execute_tool(
        "update_jira_ticket",
        {"ticket_id": "RIVER-123", "summary": "Updated title"},
        context,
    )

    assert result["approval_required"] is True
    assert result["change_preview"]["kind"] == "jira_update"
    assert result["change_preview"]["after"]["summary"] == "Updated title"
    preview = (
        await db.execute(select(ChangePreview).where(ChangePreview.approval_id == result["approval_id"]))
    ).scalar_one()
    assert preview.tool_name == "update_jira_ticket"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_create_jira_release_bundle_creates_version_and_tickets(monkeypatch):
    observed_posts: list[tuple[str, dict[str, Any]]] = []
    observed_puts: list[tuple[str, dict[str, Any]]] = []

    async def fake_jira_api_get(client, jira_url, path, headers=None, params=None):
        if path == "/project/ACME/versions":
            return [], "3"
        if path == "/project/ACME":
            return {
                "issueTypes": [
                    {"name": "Technical task", "subtask": True},
                    {"name": "Improvement", "subtask": False},
                    {"name": "Bug", "subtask": False},
                ]
            }, "3"
        if path == "/priority":
            return [
                {"name": "Blocker"},
                {"name": "Critical"},
                {"name": "Major"},
                {"name": "Minor"},
                {"name": "Trivial"},
            ], "3"
        raise AssertionError(path)

    async def fake_jira_api_post(client, jira_url, path, headers=None, payload=None):
        observed_posts.append((path, payload or {}))
        if path == "/version":
            return {"id": "2001", "name": "ai-test-01"}, "3", 201
        if path == "/issue":
            str(((payload or {}).get("fields") or {}).get("summary") or "")
            suffix = len([item for item in observed_posts if item[0] == "/issue"])
            return {"id": f"300{suffix}", "key": f"ACME-{suffix}"}, "3", 201
        raise AssertionError(path)

    async def fake_jira_api_put(client, jira_url, path, headers=None, payload=None):
        observed_puts.append((path, payload or {}))
        return 204

    async def fake_search_users(client, jira_url, *, headers, query, project_key, limit):
        assert project_key == "ACME"
        return ([{"name": "alice", "displayName": "Alice Example", "emailAddress": "alice@example.com"}], "2")

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_jira_api_get)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_post", fake_jira_api_post)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_put", fake_jira_api_put)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_search_users_raw", fake_search_users)

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

    result = await CreateJiraReleaseBundle().execute(
        {
            "project_key": "ACME",
            "release_name": "ai-test-01",
            "release_now": True,
            "release_date": "2026-04-14",
            "tickets": [
                {"summary": "AI test 01 - ticket 1", "assignee": "alice"},
                {"summary": "AI test 01 - ticket 2", "labels": ["ai-test-01"], "issue_type": "Task"},
                {"summary": "AI test 01 - ticket 3", "priority": "High"},
            ],
        },
        context,
    )

    assert result["version_id"] == "2001"
    assert result["version_created"] is True
    assert result["release_date"] == "2026-04-14"
    assert result["created_ticket_count"] == 3
    assert result["release_status"] == "released"
    assert observed_posts[0][0] == "/version"
    assert len([item for item in observed_posts if item[0] == "/issue"]) == 3
    created_issue_payloads = [item[1] for item in observed_posts if item[0] == "/issue"]
    assert created_issue_payloads[0]["fields"]["assignee"] == {"name": "alice"}
    assert created_issue_payloads[1]["fields"]["issuetype"] == {"name": "Improvement"}
    assert created_issue_payloads[2]["fields"]["priority"] == {"name": "Major"}
    assert all(payload["fields"]["fixVersions"] == [{"id": "2001"}] for payload in created_issue_payloads)
    assert observed_puts == [("/version/2001", {"released": True, "releaseDate": "2026-04-14"})]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_create_jira_release_bundle_updates_existing_version_release_date(monkeypatch):
    observed_puts: list[tuple[str, dict[str, Any]]] = []
    observed_posts: list[tuple[str, dict[str, Any]]] = []

    async def fake_jira_api_get(client, jira_url, path, headers=None, params=None):
        if path == "/project/ACME/versions":
            return [{"id": "45364", "name": "ai-release-02", "releaseDate": "2026-04-14"}], "3"
        if path == "/project/ACME":
            return {"issueTypes": [{"name": "Improvement", "subtask": False}]}, "3"
        if path == "/priority":
            return [{"name": "Major"}], "3"
        raise AssertionError(path)

    async def fake_jira_api_post(client, jira_url, path, headers=None, payload=None):
        observed_posts.append((path, payload or {}))
        if path == "/issue":
            suffix = len(observed_posts)
            return {"id": f"300{suffix}", "key": f"ACME-{suffix}"}, "3", 201
        raise AssertionError(path)

    async def fake_jira_api_put(client, jira_url, path, headers=None, payload=None):
        observed_puts.append((path, payload or {}))
        return 204

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_jira_api_get)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_post", fake_jira_api_post)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_put", fake_jira_api_put)

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
        current_user_message="create a new release named ai-release-02. The release date is in 2 weeks.",
    )
    today = datetime.now().astimezone().date().isoformat()
    expected = (datetime.now().astimezone().date() + timedelta(days=14)).isoformat()

    result = await CreateJiraReleaseBundle().execute(
        {
            "project_key": "ACME",
            "release_name": "ai-release-02",
            "release_date": today,
            "tickets": [{"summary": "Enhance AWS environment monitoring"}],
        },
        context,
    )

    assert result["version_id"] == "45364"
    assert result["version_created"] is False
    assert result["release_date"] == expected
    assert observed_puts[0] == ("/version/45364", {"releaseDate": expected})
    assert observed_posts[0][0] == "/issue"
