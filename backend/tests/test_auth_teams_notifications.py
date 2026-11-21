"""Team membership and project grants, notification templates, subscriptions and the delivery worker."""

import pytest
from sqlalchemy import select

from app.models import Notification, NotificationDeliveryLog, Project, TeamMember, TeamProject
from app.plugins import plugin_manager
from app.services.notification_delivery import process_notification_delivery_batch
from tests.conftest import ADMIN_PASSWORD


async def _register_user(client, auth_headers, username: str, display_name: str) -> str:
    create_user_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "testpass123",
            "display_name": display_name,
        },
        headers=auth_headers,
    )
    assert create_user_resp.status_code == 200
    return create_user_resp.json()["id"]


async def _login_headers(client, username: str) -> dict[str, str]:
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": "testpass123"},
    )
    assert login_resp.status_code == 200
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


async def _create_team_with_member_and_project(client, auth_headers, db, teammate_id: str) -> tuple[str, str]:
    """Create a team, add the teammate as viewer and grant the first project; return (team id, project id)."""
    create_team_resp = await client.post(
        "/api/v1/teams",
        json={"name": "Platform Crew", "description": "Primary platform team"},
        headers=auth_headers,
    )
    assert create_team_resp.status_code == 200
    team_payload = create_team_resp.json()
    assert team_payload["name"] == "Platform Crew"
    team_id = team_payload["id"]

    add_member_resp = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": teammate_id, "role": "viewer"},
        headers=auth_headers,
    )
    assert add_member_resp.status_code == 200

    project = (await db.execute(select(Project.id).order_by(Project.name.asc()))).first()
    assert project is not None
    project_id = project[0]
    grant_project_resp = await client.post(
        f"/api/v1/teams/{team_id}/projects",
        json={"project_id": project_id, "role": "member"},
        headers=auth_headers,
    )
    assert grant_project_resp.status_code == 200
    return team_id, project_id


async def _assert_team_rows(db, team_id: str, teammate_id: str, project_id: str) -> None:
    membership = (
        await db.execute(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == teammate_id))
    ).scalar_one_or_none()
    assert membership is not None
    assert membership.role == "viewer"
    team_project = (
        await db.execute(
            select(TeamProject).where(TeamProject.team_id == team_id, TeamProject.project_id == project_id)
        )
    ).scalar_one_or_none()
    assert team_project is not None


@pytest.mark.asyncio
async def test_team_creation_membership_project_grant_and_notifications(client, auth_headers, db):
    teammate_id = await _register_user(client, auth_headers, "teammate", "Team Mate")

    team_id, project_id = await _create_team_with_member_and_project(client, auth_headers, db, teammate_id)

    await _assert_team_rows(db, team_id, teammate_id, project_id)

    teammate_headers = await _login_headers(client, "teammate")

    notifications_resp = await client.get("/api/v1/notifications", headers=teammate_headers)
    assert notifications_resp.status_code == 200
    notifications = notifications_resp.json()
    team_notification = next(item for item in notifications if item["type"] == "team.member_added")
    notification_id = team_notification["id"]

    read_resp = await client.patch(f"/api/v1/notifications/{notification_id}/read", headers=teammate_headers)
    assert read_resp.status_code == 200
    assert read_resp.json()["is_read"] is True

    prefs_resp = await client.get("/api/v1/notifications/preferences", headers=teammate_headers)
    assert prefs_resp.status_code == 200
    assert prefs_resp.json()["in_app_enabled"] is True

    update_prefs_resp = await client.put(
        "/api/v1/notifications/preferences",
        json={"in_app_enabled": True, "email_enabled": True, "slack_enabled": False, "teams_enabled": True},
        headers=teammate_headers,
    )
    assert update_prefs_resp.status_code == 200
    assert update_prefs_resp.json()["email_enabled"] is True
    assert update_prefs_resp.json()["teams_enabled"] is True

    db_notifications = (
        (await db.execute(select(Notification).where(Notification.user_id == teammate_id))).scalars().all()
    )
    assert db_notifications


async def _seed_notify_user_and_project(client, auth_headers, db) -> tuple[str, str, str]:
    """Register the notify user and pick the first project; return (user id, project id, project name)."""
    create_user_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "notify-user",
            "email": "notify-user@example.com",
            "password": "testpass123",
            "display_name": "Notify User",
        },
        headers=auth_headers,
    )
    assert create_user_resp.status_code == 200
    notify_user_id = create_user_resp.json()["id"]

    project_row = (await db.execute(select(Project.id, Project.name).order_by(Project.name.asc()))).first()
    assert project_row is not None
    project_id = project_row[0]
    project_name = project_row[1]
    return notify_user_id, project_id, project_name


async def _login_and_enable_email(client, username: str) -> None:
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": "testpass123"},
    )
    assert login_resp.status_code == 200
    user_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}
    prefs_resp = await client.put(
        "/api/v1/notifications/preferences",
        json={"in_app_enabled": True, "email_enabled": True, "slack_enabled": False, "teams_enabled": False},
        headers=user_headers,
    )
    assert prefs_resp.status_code == 200


async def _create_email_template_and_subscription(client, auth_headers, notify_user_id: str, project_id: str) -> str:
    """Create the approval email template and the user's subscription to it; return the subscription id."""
    template_resp = await client.post(
        "/admin/notification-templates",
        json={
            "name": "Approval email",
            "event_type": "approval.requested",
            "channel_type": "email",
            "project_id": project_id,
            "subject_template": "Approval required: {{ notification.title }}",
            "body_template": "Project={{ project.name }} Ticket={{ payload.ticket_id }} Link={{ notification.link }}",
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert template_resp.status_code == 200
    template_id = template_resp.json()["id"]

    subscription_resp = await client.post(
        "/admin/notification-subscriptions",
        json={
            "user_id": notify_user_id,
            "project_id": project_id,
            "event_type": "approval.requested",
            "channel_type": "email",
            "target": "notify-user@example.com",
            "template_id": template_id,
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert subscription_resp.status_code == 200
    return subscription_resp.json()["id"]


async def _notify_approval_requested(db, notify_user_id: str, project_id: str) -> None:
    from app.services.team_notification import create_notification

    await create_notification(
        db,
        user_id=notify_user_id,
        notification_type="approval.requested",
        title="Approve branch push",
        body="A change is waiting.",
        link="/admin/chat?session_id=abc",
        payload={"ticket_id": "OCX-123"},
        project_id=project_id,
    )
    await db.commit()


async def _assert_panel_log_needs_admin_login(client, log_id: str, project_name: str) -> None:
    unauth_panel_log_resp = await client.get("/admin/chat/api/panel/channel-delivery-log")
    assert unauth_panel_log_resp.status_code == 401

    login_admin_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_admin_resp.status_code == 303
    panel_log_resp = await client.get("/admin/chat/api/panel/channel-delivery-log")
    assert panel_log_resp.status_code == 200
    panel_log = panel_log_resp.json()
    assert any(item["id"] == log_id and item["project_name"] == project_name for item in panel_log)


def _stub_email_channel(monkeypatch, sent_messages: list) -> None:
    class FakeChannel:
        async def send_message(self, target: str, content: str, **kwargs):
            sent_messages.append((target, kwargs.get("subject"), content))
            return True

    monkeypatch.setattr(
        plugin_manager,
        "get_single_channel_for_plugin",
        lambda plugin_id: ("email-live", FakeChannel()) if plugin_id == "email" else None,
    )


@pytest.mark.asyncio
async def test_notification_templates_subscriptions_and_delivery_worker(client, auth_headers, db, monkeypatch):
    notify_user_id, project_id, project_name = await _seed_notify_user_and_project(client, auth_headers, db)

    subscription_id = await _create_email_template_and_subscription(client, auth_headers, notify_user_id, project_id)

    await _login_and_enable_email(client, "notify-user")

    await _notify_approval_requested(db, notify_user_id, project_id)

    logs = (
        (
            await db.execute(
                select(NotificationDeliveryLog).where(NotificationDeliveryLog.subscription_id == subscription_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].status == "pending"
    assert logs[0].subject == "Approval required: Approve branch push"
    assert "Ticket=OCX-123" in logs[0].body

    await _assert_panel_log_needs_admin_login(client, logs[0].id, project_name)

    sent_messages: list[tuple[str, str | None, str]] = []
    _stub_email_channel(monkeypatch, sent_messages)
    processed = await process_notification_delivery_batch(db)
    assert processed == 1
    await db.refresh(logs[0])
    assert logs[0].status == "sent"
    assert sent_messages == [("notify-user@example.com", "Approval required: Approve branch push", logs[0].body)]

    admin_log_resp = await client.get("/admin/notification-log", headers=auth_headers)
    assert admin_log_resp.status_code == 200
    assert any(item["id"] == logs[0].id for item in admin_log_resp.json())
