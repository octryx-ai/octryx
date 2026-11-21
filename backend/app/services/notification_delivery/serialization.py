from __future__ import annotations

from typing import Any

from ...models import NotificationDeliveryLog, NotificationSubscription, NotificationTemplate
from ...models.json_text import safe_json_dict


def serialize_notification_template(row: NotificationTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "event_type": row.event_type,
        "channel_type": row.channel_type,
        "project_id": row.project_id,
        "subject_template": row.subject_template,
        "body_template": row.body_template,
        "is_active": bool(row.is_active),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_notification_subscription(row: NotificationSubscription) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "project_id": row.project_id,
        "event_type": row.event_type,
        "channel_type": row.channel_type,
        "channel_config_id": row.channel_config_id,
        "target": row.target,
        "template_id": row.template_id,
        "is_active": bool(row.is_active),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_notification_log(row: NotificationDeliveryLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "notification_id": row.notification_id,
        "subscription_id": row.subscription_id,
        "template_id": row.template_id,
        "user_id": row.user_id,
        "project_id": row.project_id,
        "event_type": row.event_type,
        "channel_type": row.channel_type,
        "channel_config_id": row.channel_config_id,
        "target": row.target,
        "subject": row.subject,
        "body": row.body,
        "payload": safe_json_dict(row.payload_json),
        "status": row.status,
        "retry_count": int(row.retry_count or 0),
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "last_error": row.last_error,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
