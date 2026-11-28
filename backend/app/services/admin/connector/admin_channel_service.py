"""Admin-panel service helpers for channel management."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import NotificationDeliveryLog, NotificationSubscription, Project
from ...access_control import require_existing_workspace
from ...notification_delivery.serialization import serialize_notification_log, serialize_notification_subscription
from ...notification_delivery.templates import validate_channel_config
from ._admin_channel_common import audit_channel

logger = logging.getLogger(__name__)


# The events this pipeline delivers to a Workspace target; creating a target for any other event is refused (400).
SUPPORTED_DELIVERY_EVENTS = {
    "approval.requested",
    "trace.alert.triggered",
}

TEAMS_TARGET_FORMAT_DETAIL = (
    "Teams target must be formatted as serviceUrl|conversationId or "
    "thread|serviceUrl|tenantId|teamId|channelId"
)


def _is_supported_teams_target(target: str) -> bool:
    if not target:
        return False
    if target.startswith("thread|"):
        parts = target.split("|")
        return len(parts) == 5 and all(part.strip() for part in parts[1:])
    parts = target.split("|", 1)
    return len(parts) == 2 and all(part.strip() for part in parts)


async def list_channel_delivery_targets(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(NotificationSubscription)
                .where(NotificationSubscription.channel_type == "teams")
                .order_by(NotificationSubscription.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [serialize_notification_subscription(row) for row in rows]


async def list_channel_delivery_logs(
    db: AsyncSession,
    *,
    limit: int = 100,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit or 100), 500))
    stmt = (
        select(NotificationDeliveryLog, Project.name.label("project_name"))
        .outerjoin(Project, Project.id == NotificationDeliveryLog.project_id)
        .order_by(NotificationDeliveryLog.created_at.desc())
        .limit(bounded_limit)
    )
    if status_filter:
        stmt = stmt.where(NotificationDeliveryLog.status == str(status_filter).strip().lower())
    rows = (await db.execute(stmt)).all()
    result = []
    for log_row, project_name in rows:
        payload = serialize_notification_log(log_row)
        payload["project_name"] = project_name
        result.append(payload)
    return result


async def create_channel_delivery_target(
    db: AsyncSession,
    *,
    body: dict[str, Any],
    admin_id: str,
) -> dict[str, Any]:
    project_id = str(body.get("project_id") or "").strip() or None
    await require_existing_workspace(db, admin_id, project_id)
    event_type = str(body.get("event_type") or "").strip()
    target = str(body.get("target") or "").strip()
    channel_config_id = body.get("channel_config_id")
    if channel_config_id in {"", 0}:
        channel_config_id = None
    if event_type not in SUPPORTED_DELIVERY_EVENTS:
        raise HTTPException(status_code=400, detail="Unsupported delivery event_type")
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")
    if not _is_supported_teams_target(target):
        raise HTTPException(status_code=422, detail=TEAMS_TARGET_FORMAT_DETAIL)
    await validate_channel_config(db, channel_type="teams", channel_config_id=channel_config_id)
    row = NotificationSubscription(
        id=str(uuid.uuid4()),
        user_id=None,
        project_id=project_id,
        event_type=event_type,
        channel_type="teams",
        channel_config_id=channel_config_id,
        target=target,
        template_id=None,
        is_active=bool(body.get("is_active", True)),
        created_by=admin_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return serialize_notification_subscription(row)


async def delete_channel_delivery_target(
    db: AsyncSession,
    *,
    target_id: str,
    admin_id: str,
) -> dict[str, Any]:
    row = await db.get(NotificationSubscription, target_id)
    if row is None or row.channel_type != "teams":
        raise HTTPException(status_code=404, detail="Teams delivery target not found")
    await audit_channel(
        db,
        user_id=admin_id,
        action="teams_delivery_target_deleted",
        channel_id=str(row.channel_config_id or "teams"),
        details={"event_type": row.event_type, "project_id": row.project_id},
    )
    await db.delete(row)
    await db.commit()
    return {"deleted": True, "id": target_id}
