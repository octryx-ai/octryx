"""User invitations and retention policies with deletion requests."""

from datetime import timedelta

import pytest
from sqlalchemy import select

import app.services.privacy.service as privacy_service_module
from app.models import (
    DataExport,
    Notification,
    Project,
    RetentionPolicy,
    Session,
    SkillUsageEvent,
    TeamMember,
    User,
    UserInvitation,
)
from app.plugins import plugin_manager
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_invitation_create_sends_email_and_accept_provisions_user(client, auth_headers, db, monkeypatch):
    sent_messages: list[tuple[str, str, str]] = []

    class FakeEmailChannel:
        async def send_message(self, target: str, content: str, **kwargs):
            sent_messages.append((target, kwargs.get("subject", ""), content))
            return True

    monkeypatch.setattr(
        plugin_manager,
        "get_single_channel_for_plugin",
        lambda plugin_id: ("email-live", FakeEmailChannel()) if plugin_id == "email" else None,
    )

    create_team_resp = await client.post(
        "/api/v1/teams",
        json={"name": "Invite Team", "description": "Invitation team"},
        headers=auth_headers,
    )
    assert create_team_resp.status_code == 200
    team_id = create_team_resp.json()["id"]

    project = (await db.execute(select(Project.id).order_by(Project.name.asc()))).first()
    assert project is not None
    project_id = project[0]

    invite_resp = await client.post(
        "/api/v1/invitations",
        json={
            "email": "invited-user@example.com",
            "team_id": team_id,
            "project_id": project_id,
            "role": "member",
            "expires_in_hours": 24,
        },
        headers=auth_headers,
    )
    assert invite_resp.status_code == 200
    invite_payload = invite_resp.json()
    assert invite_payload["delivery_method"] == "email"
    token = invite_payload["invite_url"].rsplit("/", 1)[-1]
    assert sent_messages and sent_messages[0][0] == "invited-user@example.com"

    accept_resp = await client.post(
        f"/api/v1/invitations/{token}/accept",
        json={
            "username": "invited-user",
            "password": "testpass123",
            "display_name": "Invited User",
        },
    )
    assert accept_resp.status_code == 200
    accepted_payload = accept_resp.json()
    assert accepted_payload["team_id"] == team_id
    assert accepted_payload["project_id"] == project_id

    invitation = (
        await db.execute(select(UserInvitation).where(UserInvitation.id == invite_payload["id"]))
    ).scalar_one_or_none()
    assert invitation is not None
    assert invitation.accepted_at is not None

    created_user = (await db.execute(select(User).where(User.username == "invited-user"))).scalar_one_or_none()
    assert created_user is not None
    membership = (
        await db.execute(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == created_user.id))
    ).scalar_one_or_none()
    assert membership is not None


@pytest.mark.asyncio
async def test_retention_policy_endpoint_and_deletion_request_processing(
    client, auth_headers, db, tmp_path, monkeypatch
):
    monkeypatch.setattr(privacy_service_module, "EXPORT_DIR", tmp_path)

    create_user_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "gdpr-user",
            "email": "gdpr-user@example.com",
            "password": "testpass123",
            "display_name": "GDPR User",
        },
        headers=auth_headers,
    )
    assert create_user_resp.status_code == 200
    target_user_id = create_user_resp.json()["id"]

    policy_resp = await client.post(
        "/admin/retention-policies",
        json={"entity_type": "notifications", "ttl_days": 1, "action": "delete", "is_active": True},
        headers=auth_headers,
    )
    assert policy_resp.status_code == 200
    assert policy_resp.json()["entity_type"] == "notifications"

    list_resp = await client.get("/admin/retention-policies", headers=auth_headers)
    assert list_resp.status_code == 200
    assert any(item["entity_type"] == "notifications" for item in list_resp.json())

    old_notification = Notification(
        user_id=target_user_id,
        type="test.old",
        title="Old notification",
        body="Old body",
        created_at=utc_now() - timedelta(days=3),
    )
    session = Session(user_id=target_user_id, agent_type="diagnosis", status="active")
    db.add_all([old_notification, session])
    await db.flush()
    skill_usage_event = SkillUsageEvent(
        event_type="search",
        query_excerpt="sensitive user query",
        returned_skill_ids=[],
        policy_status="success",
        user_id=target_user_id,
        session_id=session.id,
    )
    db.add(skill_usage_event)
    await db.commit()

    request_resp = await client.post(
        "/admin/deletion-requests",
        json={"target_user_id": target_user_id, "reason": "GDPR delete"},
        headers=auth_headers,
    )
    assert request_resp.status_code == 200
    assert request_resp.json()["status"] == "pending"

    affected = await privacy_service_module.apply_retention_policies(db)
    assert affected >= 1

    processed = await privacy_service_module.process_pending_deletion_requests(db)
    assert processed == 1

    updated_user = (await db.execute(select(User).where(User.id == target_user_id))).scalar_one()
    assert updated_user.is_active is False
    assert updated_user.username.startswith("deleted-user-")
    remaining_skill_usage = (
        await db.execute(select(SkillUsageEvent).where(SkillUsageEvent.user_id == target_user_id))
    ).scalars().all()
    assert remaining_skill_usage == []
    exports = (await db.execute(select(DataExport).where(DataExport.target_user_id == target_user_id))).scalars().all()
    assert exports
    assert tmp_path.joinpath(f"{exports[0].id}.json").exists()
    policies = (
        (await db.execute(select(RetentionPolicy).where(RetentionPolicy.entity_type == "notifications")))
        .scalars()
        .all()
    )
    assert policies
