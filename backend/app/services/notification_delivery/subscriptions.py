from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notification_delivery.access import require_admin_user
from app.services.notification_delivery.serialization import (
    serialize_notification_log,
    serialize_notification_subscription,
)
from app.services.notification_delivery.templates import normalize_channel_type, validate_channel_config

from ...models import (
    NotificationDeliveryLog,
    NotificationPreference,
    NotificationSubscription,
    NotificationTemplate,
    Project,
    User,
)


async def list_notification_subscriptions(
    db: AsyncSession,
    *,
    current_user: User,
    admin_scope: bool = False,
) -> list[dict[str, Any]]:
    stmt = select(NotificationSubscription).order_by(NotificationSubscription.created_at.desc())
    if not admin_scope:
        stmt = stmt.where(NotificationSubscription.user_id == current_user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_notification_subscription(row) for row in rows]


async def upsert_notification_subscription(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
    subscription_id: str | None = None,
    admin_scope: bool = False,
) -> dict[str, Any]:
    if admin_scope:
        await require_admin_user(db, current_user)
        user_id = str(payload.get("user_id") or "").strip() or None
        project_id = str(payload.get("project_id") or "").strip() or None
    else:
        user_id = current_user.id
        project_id = str(payload.get("project_id") or "").strip() or None
    if not user_id and not project_id:
        raise HTTPException(status_code=422, detail="Either user_id or project_id is required")
    # An unknown id failed at commit with a foreign-key error.
    if project_id and await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if user_id and await db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if subscription_id:
        row = await db.get(NotificationSubscription, subscription_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Notification subscription not found")
        if not admin_scope and row.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Cannot modify another user's subscription")
    else:
        row = NotificationSubscription(id=str(uuid.uuid4()), created_by=current_user.id)
        db.add(row)
    row.user_id = user_id
    row.project_id = project_id
    row.event_type = str(payload.get("event_type") or "").strip() or "*"
    row.channel_type = normalize_channel_type(payload.get("channel_type"))
    row.target = str(payload.get("target") or "").strip()
    row.channel_config_id = payload.get("channel_config_id")
    row.template_id = str(payload.get("template_id") or "").strip() or None
    row.is_active = bool(payload.get("is_active", True))
    if not row.target:
        raise HTTPException(status_code=422, detail="target is required")
    await validate_channel_config(db, channel_type=row.channel_type, channel_config_id=row.channel_config_id)
    if row.template_id:
        template = await db.get(NotificationTemplate, row.template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Notification template not found")
        if template.channel_type != row.channel_type:
            raise HTTPException(status_code=400, detail="Template channel_type does not match subscription")
    await db.commit()
    await db.refresh(row)
    return serialize_notification_subscription(row)


async def delete_notification_subscription(
    db: AsyncSession,
    *,
    current_user: User,
    subscription_id: str,
    admin_scope: bool = False,
) -> dict[str, Any]:
    row = await db.get(NotificationSubscription, subscription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification subscription not found")
    if admin_scope:
        await require_admin_user(db, current_user)
    elif row.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot delete another user's subscription")
    # Its delivery log stays (who was told what) but no longer points at it: notification_log.subscription_id has a
    # foreign key without ON DELETE, so the reference is cleared before the subscription is deleted.
    await db.execute(update(NotificationDeliveryLog).where(NotificationDeliveryLog.subscription_id == row.id)
                     .values(subscription_id=None))
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "id": subscription_id}


TEST_EVENT = "notification.test"


async def send_test_delivery(
    db: AsyncSession,
    *,
    current_user: User,
    subscription_id: str,
    admin_scope: bool = False,
) -> dict[str, Any]:
    """Queue one test message for the subscription; the delivery worker sends it like any other (the settings
    page needs "send a test"). Channel switches do not apply: the person asked for it."""
    import json

    row = await db.get(NotificationSubscription, subscription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification subscription not found")
    if admin_scope:
        await require_admin_user(db, current_user)
    elif row.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot test another user's subscription")
    who = current_user.display_name or current_user.username
    subject = "Octryx test notification"
    body = f"{who} sent this test to check the {row.channel_type} subscription for '{row.event_type}'."
    log = NotificationDeliveryLog(
        id=str(uuid.uuid4()), notification_id=None, subscription_id=row.id, template_id=None,
        user_id=row.user_id or current_user.id, project_id=row.project_id, event_type=TEST_EVENT,
        channel_type=row.channel_type, channel_config_id=row.channel_config_id, target=row.target, subject=subject,
        body=body, payload_json=json.dumps({"notification": {"type": TEST_EVENT, "title": subject, "body": body}}),
        status="pending", last_error=None,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return serialize_notification_log(log)


async def list_notification_log(
    db: AsyncSession,
    *,
    current_user: User,
    admin_scope: bool = False,
    status_filter: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = (
        select(NotificationDeliveryLog)
        .order_by(NotificationDeliveryLog.created_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    if status_filter:
        stmt = stmt.where(NotificationDeliveryLog.status == str(status_filter).strip().lower())
    if not admin_scope:
        stmt = stmt.where(NotificationDeliveryLog.user_id == current_user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_notification_log(row) for row in rows]


def delivery_allowed_by_preferences(subscription: NotificationSubscription, pref: NotificationPreference) -> bool:
    """The person's channel switches gate their catch-all (``*``) subscriptions. A subscription to one event type is
    its own switch (``is_active``): otherwise switching email on for problem alerts would switch it on for
    every other email subscription of the person too."""
    if str(subscription.event_type or "*").strip() not in ("", "*"):
        return True
    if subscription.channel_type == "email":
        return bool(pref.email_enabled)
    if subscription.channel_type == "slack":
        return bool(pref.slack_enabled)
    if subscription.channel_type == "teams":
        return bool(pref.teams_enabled)
    return False
