"""Tests for basic chat endpoints: page renders, bootstrap, login rate limiting, bearer auth, and delete session."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, User
from app.services.session.run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_chat_page_renders(client):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    page_resp = await client.get("/chat?new=true")
    assert page_resp.status_code == 200
    assert '<div id="root"></div>' in page_resp.text
    assert "/static/chat/assets/" in page_resp.text

    bootstrap_resp = await client.get("/chat/api/bootstrap?new=true")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    assert payload["newThread"] is True
    assert payload["selectedSession"] is None
    # "Automatic · <model display name>".
    assert payload["selectedRuntimeLabel"].startswith("Automatic · ")
    assert payload["selectedThinkingLevel"] == "light"
    assert any(mode["key"] == "diagnosis" for mode in payload["agentModes"])
    assert payload["archivedThreadCount"] == 0
    assert payload["selectedProjectId"] == ""
    assert payload["selectedThreadStats"] is None
    assert "selectedPlaybookId" not in payload
    assert payload["selectedAgentId"] == ""
    assert payload["selectedAgentName"] == ""
    assert payload["selectedAgentSelectionSource"] == ""
    assert payload["selectedAgentType"] == "diagnosis"
    assert payload["launchSurface"]["primary_controls"] == ["runtime", "project", "thinking"]
    assert payload["launchSurface"]["advanced_controls"] == []
    assert payload["launchSurface"]["allow_advanced_overrides"] is False
    assert payload["launchSurface"]["role_scope"] == "admin"




@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_login_rate_limited_after_five_failed_attempts(client):
    for _ in range(5):
        resp = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "wrong"},
        )
        assert resp.status_code == 401

    resp = await client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 429
    assert resp.headers["Retry-After"]
    assert "Too many login attempts." in resp.text


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_chat_bootstrap_accepts_bearer_auth(client, auth_headers):
    resp = await client.get("/admin/chat/api/bootstrap?new=true", headers=auth_headers)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["newThread"] is True
    assert payload["currentUser"]["username"] == "admin"


@pytest.mark.asyncio
async def test_chat_bootstrap_uses_ack_state_when_explicit_run_status_is_in_progress(client, auth_headers, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        agent_type="coding",
        status="active",
        metadata_={"title": "Active run status without running session status"},
    )
    set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    db.add(session)
    await db.commit()

    resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.headers["X-Chat-Bootstrap-Kind"] == "running_ack"
    payload = resp.json()
    assert payload["selectedSession"]["id"] == session.id
    assert payload["selectedSession"]["runStatus"] == RUN_STATUS_IN_PROGRESS
    assert payload["selectedSessionIsRunning"] is True
    assert payload["activeThreadGroups"] is None


@pytest.mark.asyncio
async def test_chat_bootstrap_hides_advanced_overrides_for_standard_user(client, auth_headers):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "viewer-bootstrap-check",
            "email": "viewer-bootstrap-check@example.com",
            "password": "testpass123",
            "display_name": "Viewer Bootstrap Check",
        },
        headers=auth_headers,
    )
    assert register_resp.status_code == 200

    viewer_login = await client.post(
        "/api/v1/auth/login",
        data={"username": "viewer-bootstrap-check", "password": "testpass123"},
    )
    assert viewer_login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}

    bootstrap_resp = await client.get("/admin/chat/api/bootstrap?new=true", headers=viewer_headers)

    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    assert payload["launchSurface"]["primary_controls"] == ["runtime", "project", "thinking"]
    assert payload["launchSurface"]["advanced_controls"] == []
    assert payload["launchSurface"]["hidden_choices"] == ["mode", "agent_group", "agent"]
    assert payload["launchSurface"]["allow_advanced_overrides"] is False
    assert payload["launchSurface"]["role_scope"] == "standard"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_chat_panel_accepts_bearer_auth(client, auth_headers):
    resp = await client.get("/admin/chat/api/panel/default-tool-sets", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["sets"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_delete_session_requires_admin_role(client, auth_headers):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "viewer-delete-check",
            "email": "viewer-delete-check@example.com",
            "password": "testpass123",
            "display_name": "Viewer Delete Check",
        },
        headers=auth_headers,
    )
    assert register_resp.status_code == 200

    viewer_login = await client.post(
        "/api/v1/auth/login",
        data={"username": "viewer-delete-check", "password": "testpass123"},
    )
    assert viewer_login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}

    session_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=viewer_headers,
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    delete_resp = await client.delete(
        f"/admin/chat/api/sessions/{session_id}",
        headers=viewer_headers,
    )
    assert delete_resp.status_code == 403
    assert delete_resp.json()["detail"] == "Admin role required"


@pytest.mark.asyncio
async def test_chat_thread_groups_report_totals_and_paginate(client, auth_headers, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    for index in range(25):
        db.add(
            Session(
                id=str(uuid.uuid4()),
                user_id=admin_user.id,
                agent_type="diagnosis",
                status="active",
                metadata_={"title": f"Paged thread {index:02d}"},
            )
        )
    await db.commit()

    bootstrap_resp = await client.get("/admin/chat/api/bootstrap?new=true", headers=auth_headers)
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    group = next(group for group in payload["activeThreadGroups"] if group["projectName"] == "No project")

    assert group["totalThreadCount"] == 25
    assert len(group["sessions"]) == 20
    assert group["nextOffset"] == 20
    assert group["hasMore"] is True

    page_resp = await client.get(
        "/admin/chat/api/thread-groups?project_id=&offset=20&limit=20",
        headers=auth_headers,
    )
    assert page_resp.status_code == 200
    page = page_resp.json()
    assert page["projectName"] == "No project"
    assert page["totalThreadCount"] == 25
    assert len(page["sessions"]) == 5
    assert page["nextOffset"] == 25
    assert page["hasMore"] is False

    count_resp = await client.get("/admin/chat/api/thread-groups/count?project_id=", headers=auth_headers)
    assert count_resp.status_code == 200
    assert count_resp.json()["count"] == 25
