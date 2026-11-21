from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.error_facts import error_text
from app.services.notification_delivery.access import channel_plugin_id, notification_preferences
from app.services.notification_delivery.constants import DELIVERY_RETRY_DELAYS_SECONDS
from app.services.notification_delivery.subscriptions import delivery_allowed_by_preferences
from app.services.notification_delivery.templates import render_template, select_template

from ...models import NotificationDeliveryLog, NotificationSubscription, Project, User
from ...models.json_text import dump_json_dict
from ...plugins import plugin_manager
from ...time_utils import utc_now


def _unfenced(title: str, body: str | None, payload: dict[str, object] | None):
    """Subject, body and payload of an outbound delivery (email, Teams, Slack, webhook) without fence markers.

    The fence is for a model's input only; a notification that carries a fenced ticket summary or
    an agent's output must reach the channel as the text itself, rendered templates included."""
    from ..content_security.knowledge_fence import unfenced_result

    return unfenced_result(title), unfenced_result(body), unfenced_result(payload)


async def _active_subscriptions(
    db: AsyncSession, notification_type: str, *scope: Any
) -> Sequence[NotificationSubscription]:
    """Active subscriptions to ``notification_type`` (or to every type) within ``scope``."""
    return (
        (
            await db.execute(
                select(NotificationSubscription).where(
                    NotificationSubscription.is_active.is_(True),
                    *scope,
                    or_(
                        NotificationSubscription.event_type == notification_type,
                        NotificationSubscription.event_type == "*",
                    ),
                )
            )
        )
        .scalars()
        .all()
    )


def _delivery_context(
    *,
    notification_type: str,
    title: str,
    body: str | None,
    link: str | None,
    payload: dict[str, object] | None,
    user: dict[str, object],
    project: Project | None,
    project_id: str | None,
) -> dict[str, Any]:
    """What a template renders: the notification, its payload, the user and the project."""
    event_payload = payload if isinstance(payload, dict) else {}
    return {
        "notification": {
            "type": notification_type,
            "title": title,
            "body": body,
            "link": link,
        },
        "payload": event_payload,
        "user": user,
        "project": {
            "id": project.id if project else project_id,
            "name": project.name if project else None,
        },
    }


async def _delivery_row(
    db: AsyncSession,
    subscription: NotificationSubscription,
    context: dict[str, Any],
    *,
    notification_id: str | None,
    user_id: str | None,
    project_id: str | None,
    notification_type: str,
    title: str,
    body: str | None,
) -> NotificationDeliveryLog:
    """The delivery of one subscription, rendered with its template (a failed render is stored as failed)."""
    template = await select_template(
        db,
        event_type=notification_type,
        channel_type=subscription.channel_type,
        project_id=project_id,
        template_id=subscription.template_id,
    )
    try:
        subject = render_template(template.subject_template, context) if template else title
        rendered_body = render_template(template.body_template, context) if template else (body or title)
        status = "pending"
        last_error = None
    except Exception as exc:
        subject = title
        rendered_body = body or title
        status = "failed"
        last_error = error_text("notification_template_render_failed", exc)

    return NotificationDeliveryLog(
        id=str(uuid.uuid4()),
        notification_id=notification_id,
        subscription_id=subscription.id,
        template_id=template.id if template else None,
        user_id=user_id,
        project_id=project_id,
        event_type=notification_type,
        channel_type=subscription.channel_type,
        channel_config_id=subscription.channel_config_id,
        target=subscription.target,
        subject=(subject or None),
        body=(rendered_body or title),
        payload_json=dump_json_dict(context),
        status=status,
        last_error=last_error,
    )


def _subscription_matches(subscription: NotificationSubscription, user_id: str, project_id: str | None) -> bool:
    matches_user = subscription.user_id == user_id and (
        subscription.project_id is None or subscription.project_id == project_id
    )
    matches_project = (
        subscription.user_id is None
        and subscription.project_id is not None
        and subscription.project_id == project_id
    )
    return matches_user or matches_project


async def enqueue_outbound_notification_deliveries(
    db: AsyncSession,
    *,
    notification_id: str | None,
    user_id: str,
    notification_type: str,
    title: str,
    body: str | None,
    link: str | None,
    payload: dict[str, object] | None = None,
    project_id: str | None = None,
) -> list[NotificationDeliveryLog]:
    title, body, payload = _unfenced(title, body, payload)
    rows = await _active_subscriptions(db, notification_type)
    if not rows:
        return []

    user = await db.get(User, user_id)
    project = await db.get(Project, project_id) if project_id else None
    pref = await notification_preferences(db, user_id)
    context = _delivery_context(
        notification_type=notification_type, title=title, body=body, link=link, payload=payload,
        user={
            "id": user.id if user else user_id,
            "username": user.username if user else None,
            "email": user.email if user else None,
            "display_name": user.display_name if user else None,
        },
        project=project, project_id=project_id,
    )

    created: list[NotificationDeliveryLog] = []
    for subscription in rows:
        if not _subscription_matches(subscription, user_id, project_id):
            continue
        if subscription.user_id == user_id and not delivery_allowed_by_preferences(subscription, pref):
            continue
        row = await _delivery_row(
            db, subscription, context, notification_id=notification_id, user_id=user_id, project_id=project_id,
            notification_type=notification_type, title=title, body=body,
        )
        db.add(row)
        created.append(row)
    await db.flush()
    return created


async def enqueue_project_notification_deliveries(
    db: AsyncSession,
    *,
    notification_type: str,
    title: str,
    body: str | None,
    link: str | None,
    payload: dict[str, object] | None = None,
    project_id: str | None = None,
) -> list[NotificationDeliveryLog]:
    if not project_id:
        return []
    title, body, payload = _unfenced(title, body, payload)
    rows = await _active_subscriptions(
        db,
        notification_type,
        NotificationSubscription.user_id.is_(None),
        NotificationSubscription.project_id == project_id,
    )
    if not rows:
        return []

    project = await db.get(Project, project_id)
    context = _delivery_context(
        notification_type=notification_type, title=title, body=body, link=link, payload=payload,
        user={"id": None, "username": None, "email": None, "display_name": None},
        project=project, project_id=project_id,
    )

    created: list[NotificationDeliveryLog] = []
    for subscription in rows:
        row = await _delivery_row(
            db, subscription, context, notification_id=None, user_id=None, project_id=project_id,
            notification_type=notification_type, title=title, body=body,
        )
        db.add(row)
        created.append(row)
    await db.flush()
    return created


def resolve_delivery_channel(row: NotificationDeliveryLog):
    plugin_id = channel_plugin_id(row.channel_type)
    if row.channel_config_id is not None:
        return plugin_manager.get_channel(str(row.channel_config_id))
    match = plugin_manager.get_single_channel_for_plugin(plugin_id)
    return match[1] if match else None


def schedule_retry(row: NotificationDeliveryLog, error: str) -> None:
    row.retry_count = int(row.retry_count or 0) + 1
    row.last_error = (error or "").strip()[:4000] or "delivery_failed"
    if row.retry_count > len(DELIVERY_RETRY_DELAYS_SECONDS):
        row.status = "dead_letter"
        row.next_retry_at = None
        return
    delay = DELIVERY_RETRY_DELAYS_SECONDS[row.retry_count - 1]
    row.status = "retrying"
    row.next_retry_at = utc_now() + timedelta(seconds=delay)


async def process_notification_delivery_batch(db: AsyncSession, *, batch_size: int = 20) -> int:
    now = utc_now()
    rows = (
        (
            await db.execute(
                select(NotificationDeliveryLog)
                .where(
                    NotificationDeliveryLog.status.in_(("pending", "retrying")),
                    or_(
                        NotificationDeliveryLog.next_retry_at.is_(None),
                        NotificationDeliveryLog.next_retry_at <= now,
                    ),
                )
                .order_by(NotificationDeliveryLog.created_at.asc())
                .limit(max(1, min(batch_size, 100)))
            )
        )
        .scalars()
        .all()
    )
    processed = 0
    for row in rows:
        channel = resolve_delivery_channel(row)
        if channel is None:
            schedule_retry(row, f"No active channel available for {row.channel_type}")
            processed += 1
            continue
        try:
            success = await channel.send_message(row.target, row.body, subject=row.subject)
        except Exception as exc:
            success = False
            row.last_error = error_text("notification_delivery_failed", exc)
        if success:
            row.status = "sent"
            row.sent_at = utc_now()
            row.next_retry_at = None
            row.last_error = None
        else:
            schedule_retry(row, row.last_error or "Delivery failed")
        processed += 1
    if processed:
        await db.commit()
    return processed
