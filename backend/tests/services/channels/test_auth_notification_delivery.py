"""Notification delivery retries to the dead letter and project team delivery targets for approvals."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import NotificationDeliveryLog, NotificationSubscription, Project, Session, User
from app.plugins import plugin_manager
from app.services.notification_delivery import process_notification_delivery_batch
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_notification_delivery_worker_retries_to_dead_letter(client, auth_headers, db, monkeypatch):
    create_user_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "notify-retry",
            "email": "notify-retry@example.com",
            "password": "testpass123",
            "display_name": "Notify Retry",
        },
        headers=auth_headers,
    )
    assert create_user_resp.status_code == 200
    notify_user_id = create_user_resp.json()["id"]

    subscription = NotificationSubscription(
        user_id=notify_user_id,
        event_type="approval.requested",
        channel_type="slack",
        target="C12345",
        created_by=notify_user_id,
        is_active=True,
    )
    db.add(subscription)
    await db.flush()
    delivery = NotificationDeliveryLog(
        notification_id=None,
        subscription_id=subscription.id,
        template_id=None,
        user_id=notify_user_id,
        project_id=None,
        event_type="approval.requested",
        channel_type="slack",
        target="C12345",
        subject=None,
        body="Retry me",
        status="pending",
    )
    db.add(delivery)
    await db.commit()

    class FailingChannel:
        async def send_message(self, target: str, content: str, **kwargs):
            return False

    monkeypatch.setattr(
        plugin_manager,
        "get_single_channel_for_plugin",
        lambda plugin_id: ("slack-live", FailingChannel()) if plugin_id == "slack" else None,
    )

    for expected_status in ("retrying", "retrying", "retrying", "dead_letter"):
        delivery.next_retry_at = utc_now() - timedelta(seconds=1)
        await db.commit()
        await process_notification_delivery_batch(db)
        await db.refresh(delivery)
        assert delivery.status == expected_status

    admin_log_resp = await client.get("/admin/notification-log?status=dead_letter", headers=auth_headers)
    assert admin_log_resp.status_code == 200
    assert any(item["id"] == delivery.id for item in admin_log_resp.json())


@pytest.mark.asyncio
async def test_project_teams_delivery_target_enqueues_once_for_approval_request(admin_client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    target_resp = await admin_client.post(
        "/admin/chat/api/panel/channel-delivery-targets",
        json={
            "project_id": project.id,
            "event_type": "approval.requested",
            "channel_type": "teams",
            "channel_config_id": None,
            "target": "https://smba.trafficmanager.net/emea/|19:approval-thread",
            "is_active": True,
        },
    )
    assert target_resp.status_code == 200, target_resp.text
    target = target_resp.json()
    assert target["channel_type"] == "teams"
    assert target["project_id"] == project.id

    session = Session(user_id=admin.id, project_id=project.id, agent_type="chat", status="running")
    db.add(session)
    await db.commit()

    from app.services.approval.request_service import ensure_approval_request

    approval = await ensure_approval_request(
        db,
        requested_by=admin.id,
        action="Approve deployment",
        reason="Worker requires human approval.",
        session_id=session.id,
    )
    await db.commit()

    logs = (
        (
            await db.execute(
                select(NotificationDeliveryLog).where(
                    NotificationDeliveryLog.subscription_id == target["id"],
                    NotificationDeliveryLog.event_type == "approval.requested",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].channel_type == "teams"
    assert logs[0].project_id == project.id
    assert logs[0].user_id is None
    assert logs[0].target == "https://smba.trafficmanager.net/emea/|19:approval-thread"
    assert "Worker requires human approval." in logs[0].body
    assert logs[0].status == "pending"
    assert approval.id

    list_resp = await admin_client.get("/admin/chat/api/panel/channel-delivery-targets")
    assert list_resp.status_code == 200
    assert any(row["id"] == target["id"] for row in list_resp.json())

    thread_target_resp = await admin_client.post(
        "/admin/chat/api/panel/channel-delivery-targets",
        json={
            "project_id": project.id,
            "event_type": "trace.alert.triggered",
            "channel_type": "teams",
            "channel_config_id": None,
            "target": "thread|https://smba.trafficmanager.net/emea/|tenant-1|team-1|channel-1",
            "is_active": True,
        },
    )
    assert thread_target_resp.status_code == 200, thread_target_resp.text
    thread_target = thread_target_resp.json()
    assert thread_target["target"] == "thread|https://smba.trafficmanager.net/emea/|tenant-1|team-1|channel-1"

    delete_resp = await admin_client.delete(f"/admin/chat/api/panel/channel-delivery-targets/{target['id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    delete_thread_resp = await admin_client.delete(f"/admin/chat/api/panel/channel-delivery-targets/{thread_target['id']}")
    assert delete_thread_resp.status_code == 200
    assert delete_thread_resp.json()["deleted"] is True
