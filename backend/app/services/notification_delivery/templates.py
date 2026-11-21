from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notification_delivery.access import channel_plugin_id, require_admin_user
from app.services.notification_delivery.constants import ALLOWED_CHANNEL_TYPES, TEMPLATE_ENV
from app.services.notification_delivery.serialization import serialize_notification_template

from ...models import ChannelConfig, NotificationTemplate, User


def normalize_channel_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in ALLOWED_CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported channel_type")
    return normalized


async def validate_channel_config(
    db: AsyncSession,
    *,
    channel_type: str,
    channel_config_id: int | None,
) -> ChannelConfig | None:
    if channel_config_id is None:
        return None
    channel = await db.get(ChannelConfig, channel_config_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel config not found")
    expected_plugin = channel_plugin_id(channel_type)
    if channel.plugin_id != expected_plugin:
        raise HTTPException(status_code=400, detail="Channel config does not match channel_type")
    return channel


async def select_template(
    db: AsyncSession,
    *,
    event_type: str,
    channel_type: str,
    project_id: str | None,
    template_id: str | None,
) -> NotificationTemplate | None:
    if template_id:
        template = await db.get(NotificationTemplate, template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Notification template not found")
        return template
    rows = (
        (
            await db.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.is_active.is_(True),
                    NotificationTemplate.channel_type == channel_type,
                    or_(NotificationTemplate.event_type == event_type, NotificationTemplate.event_type == "*"),
                    or_(NotificationTemplate.project_id == project_id, NotificationTemplate.project_id.is_(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    rows = sorted(
        rows,
        key=lambda item: (
            0 if item.project_id == project_id and item.project_id is not None else 1,
            0 if item.event_type == event_type else 1,
            item.created_at.isoformat() if item.created_at else "",
        ),
    )
    return rows[0]


def render_template(value: str | None, context: dict[str, Any]) -> str | None:
    if value is None:
        return None
    rendered = TEMPLATE_ENV.from_string(value).render(**context)
    return str(rendered).strip()


async def list_notification_templates(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(NotificationTemplate).order_by(
                    NotificationTemplate.event_type.asc(),
                    NotificationTemplate.channel_type.asc(),
                    NotificationTemplate.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [serialize_notification_template(row) for row in rows]


async def upsert_notification_template(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
    template_id: str | None = None,
) -> dict[str, Any]:
    await require_admin_user(db, current_user)
    channel_type = normalize_channel_type(payload.get("channel_type"))
    if template_id:
        row = await db.get(NotificationTemplate, template_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Notification template not found")
    else:
        row = NotificationTemplate(id=str(uuid.uuid4()), created_by=current_user.id)
        db.add(row)
    row.name = str(payload.get("name") or "").strip()
    row.event_type = str(payload.get("event_type") or "").strip() or "*"
    row.channel_type = channel_type
    row.project_id = str(payload.get("project_id") or "").strip() or None
    row.subject_template = str(payload.get("subject_template") or "").strip() or None
    row.body_template = str(payload.get("body_template") or "").strip()
    row.is_active = bool(payload.get("is_active", True))
    if not row.name or not row.body_template:
        raise HTTPException(status_code=422, detail="name and body_template are required")
    await db.commit()
    await db.refresh(row)
    return serialize_notification_template(row)


async def delete_notification_template(db: AsyncSession, *, current_user: User, template_id: str) -> dict[str, Any]:
    await require_admin_user(db, current_user)
    row = await db.get(NotificationTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification template not found")
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "id": template_id}
