"""Notification subscriptions for problem alerts: a subscription to one event is its own switch, an unknown
Workspace is a 404 not a 500, and "send a test" exists."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import NotificationDeliveryLog, User
from app.services.team_notification.service import create_notification
from tests.policy_engine_support import bearer


async def _person(db) -> User:
    user = User(id=str(uuid.uuid4()), username=f"p-{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4()}@example.test",
                password_hash="!")
    db.add(user)
    await db.commit()
    return user


async def _subscribe(client, user: User, event_type: str, target: str) -> dict:
    response = await client.post("/api/v1/notifications/subscriptions", headers=bearer(user.id),
                                 json={"event_type": event_type, "channel_type": "email", "target": target})
    assert response.status_code == 200, response.text
    return response.json()


async def _logs(db, user: User) -> list[NotificationDeliveryLog]:
    return list((await db.execute(select(NotificationDeliveryLog).where(
        NotificationDeliveryLog.user_id == user.id))).scalars())


@pytest.mark.asyncio
async def test_a_problem_alert_subscription_counts_on_its_own_while_the_catch_all_stays_switched_off(client, db):
    user = await _person(db)  # email switch off (the default)
    problems = await _subscribe(client, user, "problem.raised", "alerts@example.test")
    await _subscribe(client, user, "*", "everything@example.test")

    await create_notification(db, user_id=user.id, notification_type="problem.raised", title="Run loops")
    await create_notification(db, user_id=user.id, notification_type="session.completed", title="Done")
    await db.commit()

    sent = [(row.event_type, row.target, row.subscription_id) for row in await _logs(db, user)]
    assert sent == [("problem.raised", "alerts@example.test", problems["id"])]


@pytest.mark.asyncio
async def test_send_a_test_queues_one_message_for_the_own_subscription_only(client, db):
    user = await _person(db)
    other = await _person(db)
    subscription = await _subscribe(client, user, "problem.raised", "alerts@example.test")

    mine = await client.post(f"/api/v1/notifications/subscriptions/{subscription['id']}/test", headers=bearer(user.id))
    theirs = await client.post(f"/api/v1/notifications/subscriptions/{subscription['id']}/test",
                               headers=bearer(other.id))

    assert mine.status_code == 200 and mine.json()["status"] == "pending"
    assert theirs.status_code == 403
    [row] = await _logs(db, user)
    assert (row.event_type, row.target, row.subscription_id) == ("notification.test", "alerts@example.test",
                                                                 subscription["id"])


@pytest.mark.asyncio
async def test_an_unknown_workspace_is_a_404_not_a_500(client, db, auth_user):
    response = await client.post("/admin/notification-subscriptions", headers=bearer(auth_user.id), json={
        "project_id": str(uuid.uuid4()), "event_type": "problem.raised", "channel_type": "email",
        "target": "team@example.test"})

    assert response.status_code == 404 and response.json()["detail"]["code"] == "project_not_found"


@pytest.mark.asyncio
async def test_a_subscription_with_deliveries_can_be_deleted_and_its_log_stays(client, db):
    user = await _person(db)
    subscription = await _subscribe(client, user, "problem.raised", "alerts@example.test")
    await client.post(f"/api/v1/notifications/subscriptions/{subscription['id']}/test", headers=bearer(user.id))

    deleted = await client.delete(f"/api/v1/notifications/subscriptions/{subscription['id']}", headers=bearer(user.id))

    assert deleted.status_code == 200, deleted.text
    [row] = await _logs(db, user)
    await db.refresh(row)
    assert (row.event_type, row.subscription_id) == ("notification.test", None)
