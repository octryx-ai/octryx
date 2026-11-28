"""What the Webhooks → Inbound page shows, in words."""

from __future__ import annotations

from collections.abc import Set
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, Task
from ...models.integration.channel_config import ChannelConfig
from ...models.integration.webhook import Webhook, WebhookEvent
from ...time_utils import ensure_utc, utc_now
from .admission import (
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_GROUPED,
    OUTCOME_STARTED,
    SETUP_ALERT_TARGETS_INVALID,
    SETUP_MESSAGES,
    action_setup_gap,
    target_required,
)
from .call_guard import REJECTED_OUTCOMES
from .normalize import POLLED_SOURCE_TYPES, SOURCE_LABELS
from .targets import workspace_alert_targets

_STARTED = (OUTCOME_STARTED, OUTCOME_COMPLETED, OUTCOME_FAILED)


def trigger_path(webhook_id: str) -> str:
    return f"/api/v1/webhooks/{webhook_id}/trigger"


def _iso(value) -> str | None:
    return ensure_utc(value).isoformat() if value else None


def serialize_event(event: WebhookEvent, *, webhook_name: str | None = None, source_type: str | None = None) -> dict:
    return {
        "id": event.id,
        "webhook_id": event.webhook_id,
        "webhook_name": webhook_name,
        "source_type": source_type,
        "received_at": _iso(event.received_at),
        "processed_at": _iso(event.processed_at),
        "outcome": event.outcome or event.status,
        "title": event.alert_title or "",
        "message": event.parsed_message or "",
        "error": event.error or "",
        "is_test": bool(event.is_test),
        "task_run_id": event.task_run_id,
        "session_id": event.session_id,
    }


async def _result_destination(db: AsyncSession, task: Task | None) -> dict[str, Any]:
    config = task.config if task is not None and isinstance(task.config, dict) else {}
    channel_id = config.get("output_channel_id")
    if not channel_id:
        return {"kind": "run_history", "label": "Run history only"}
    try:
        channel = await db.get(ChannelConfig, int(channel_id))
    except (TypeError, ValueError):
        channel = None
    if channel is None:
        return {"kind": "missing_channel", "label": "Output channel no longer exists"}
    return {"kind": "channel", "plugin_id": channel.plugin_id, "label": channel.name}


async def _week_counts(db: AsyncSession, webhook: Webhook) -> dict[Any, Any]:
    week_ago = utc_now() - timedelta(days=7)
    return dict(
        (
            await db.execute(
                select(WebhookEvent.outcome, func.count())
                .where(WebhookEvent.webhook_id == webhook.id, WebhookEvent.received_at >= week_ago,
                       WebhookEvent.is_test.is_(False),
                       # Refused calls are not alerts: forged traffic never inflates the count.
                       WebhookEvent.outcome.not_in(REJECTED_OUTCOMES))
                .group_by(WebhookEvent.outcome)
            )
        ).all()
    )


async def _last_event(db: AsyncSession, webhook: Webhook) -> WebhookEvent | None:
    return (
        await db.execute(
            select(WebhookEvent).where(WebhookEvent.webhook_id == webhook.id)
            .order_by(WebhookEvent.received_at.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def serialize_webhook(db: AsyncSession, webhook: Webhook) -> dict[str, Any]:
    task = await db.get(Task, webhook.task_id) if webhook.task_id else None
    project = await db.get(Project, webhook.project_id) if webhook.project_id else None
    gap = action_setup_gap(webhook, task)
    required = target_required(task)
    targets, target_errors = await workspace_alert_targets(db, webhook.project_id) if required else ([], [])
    if gap is None and required and target_errors:
        gap = SETUP_ALERT_TARGETS_INVALID  # every alert would wait: say so on the card, not only per alert
    counts = await _week_counts(db, webhook)
    last = await _last_event(db, webhook)
    config = task.config if task is not None and isinstance(task.config, dict) else {}
    state = "paused" if not webhook.is_active else "needs_setup" if gap else "active"
    return {
        "id": webhook.id,
        "name": webhook.name,
        "description": webhook.description or "",
        "project_id": webhook.project_id,
        "workspace_name": project.name if project else "",
        "source_type": webhook.source_type or "generic",
        "source_label": SOURCE_LABELS.get(webhook.source_type or "generic", "Any JSON"),
        "polled": (webhook.source_type or "") in POLLED_SOURCE_TYPES,
        "is_active": bool(webhook.is_active),
        "has_secret": bool(webhook.secret_ref or webhook.secret),
        "trigger_path": trigger_path(webhook.id),
        "task_id": webhook.task_id,
        "action": {
            "id": task.id,
            "name": task.name,
            "workflow": str(config.get("capability_class") or ""),
        } if task is not None else None,
        "result_to": await _result_destination(db, task),
        "state": state,
        "setup_gap": gap,
        "setup_message": SETUP_MESSAGES.get(gap or "", ""),
        "alert_filter": webhook.alert_filter or "critical_warning",
        "group_window_minutes": int(webhook.group_window_minutes or 0),
        "rate_limit_per_hour": int(webhook.rate_limit_per_hour or 0),
        "poll_query": webhook.poll_query or "",
        "accept_untimestamped": bool(webhook.accept_untimestamped),
        # Whether the Action starts only for alerts mapped to one of the Workspace's alert targets.
        "alert_target": {"required": required, "targets": len(targets), "invalid": bool(target_errors)},
        "last_polled_at": _iso(webhook.last_polled_at),
        "week": {
            "alerts": int(sum(counts.values())),
            "grouped": int(counts.get(OUTCOME_GROUPED, 0)),
            "started": int(sum(counts.get(outcome, 0) for outcome in _STARTED)),
        },
        "last_event": serialize_event(last) if last else None,
        "created_at": _iso(webhook.created_at),
    }


async def list_events(db: AsyncSession, *, hidden: Set[str], webhook_id: str | None = None,
                      limit: int = 20) -> list[dict]:
    query = (
        select(WebhookEvent, Webhook.name, Webhook.source_type)
        .join(Webhook, Webhook.id == WebhookEvent.webhook_id)
        .where(Webhook.project_id.is_(None) | Webhook.project_id.not_in(hidden))
        .order_by(WebhookEvent.received_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    if webhook_id:
        query = query.where(WebhookEvent.webhook_id == webhook_id)
    rows = (await db.execute(query)).all()
    return [serialize_event(event, webhook_name=name, source_type=source) for event, name, source in rows]


__all__ = ["list_events", "serialize_event", "serialize_webhook", "trigger_path"]
