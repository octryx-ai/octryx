"""Admin-panel service for inbound webhooks (automation V3: a webhook starts an Action).

The secret is write-only: issued encrypted, returned once on create and on *Rotate*, never listed.
A webhook names the Action it starts; the Action must belong to the same Workspace. Filters, repeat
grouping and limits default to safe values (critical/warning firing alerts, 30 min, 20 per hour).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, Project, Task
from ....models.integration.webhook import Webhook
from ...agent_mode.authoring import require_explicit_agent_mode
from ...inbound_alerts.admission import ALERT_FILTERS
from ...inbound_alerts.normalize import SOURCE_TYPES
from ...inbound_alerts.samples import sample_payload
from ...inbound_alerts.signature import sign_timestamped
from ...inbound_alerts.trigger import receive_alert
from ...inbound_alerts.views import list_events, serialize_webhook
from ...webhook_secret import issue_webhook_secret, resolve_webhook_secret


async def _load(db: AsyncSession, webhook_id: str) -> Webhook:
    webhook = (await db.execute(select(Webhook).where(Webhook.id == webhook_id))).scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


def _source(value: Any) -> str:
    source = str(value or "generic").strip() or "generic"
    if source not in SOURCE_TYPES:
        raise HTTPException(status_code=422, detail={"code": "webhook_source_unsupported",
                                                     "message": "Choose one of the listed sources."})
    return source


def _alert_filter(value: Any) -> str:
    chosen = str(value or "critical_warning")
    if chosen not in ALERT_FILTERS:
        raise HTTPException(status_code=422, detail={"code": "webhook_filter_unsupported",
                                                     "message": "Choose one of the listed filters."})
    return chosen


async def _action(db: AsyncSession, task_id: Any, project_id: str) -> str | None:
    task_id = str(task_id or "").strip()
    if not task_id:
        return None
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if str(task.project_id or "") != project_id:
        raise HTTPException(status_code=422, detail={"code": "webhook_action_other_workspace",
                                                     "message": "Choose an action of the same Workspace."})
    return task.id


async def _agent_mode(db: AsyncSession, payload: dict[str, Any]) -> str | None:
    """An explicitly sent mode is held to the Action contract: a non-key is a 422, never the default.

    The forms do not send one (a webhook starts an Action); ``None`` counts as omitted.
    """
    if payload.get("agent_type") is None:
        return None
    return await require_explicit_agent_mode(db, payload["agent_type"])


# Git hosts and CI servers sign a call without a timestamp (GitHub X-Hub-Signature-256, GitLab X-Gitlab-Token,
# Bitbucket X-Hub-Signature): a timestamped-only webhook of these sources refused every call with 401
# timestamp_required. Their signature or token is still required.
HOST_SIGNED_SOURCES = frozenset({"scm_pull_request", "ci_build"})


def _untimestamped(payload: dict[str, Any]) -> bool:
    if _source(payload.get("source_type")) in HOST_SIGNED_SOURCES:
        return True
    return bool(payload.get("accept_untimestamped", False))


def _rate_limit(value: Any, default: int) -> int:
    """1–1000 analyses per hour; there is no unlimited (a replay burst must hit a ceiling)."""
    if value is None:
        return default
    limit = int(value)
    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=422, detail={"code": "webhook_rate_limit_invalid",
                                                     "message": "Choose between 1 and 1000 analyses per hour."})
    return limit


async def _set_result_channel(db: AsyncSession, task_id: str, channel_id: Any) -> None:
    """The webhook form's "Send the result to": the Action's own destination (one declaration)."""
    from ....models.integration.channel_config import ChannelConfig

    task = await db.get(Task, task_id)
    config = dict(task.config or {}) if task is not None else {}
    if channel_id in (None, ""):
        config.pop("output_channel_id", None)
    else:
        channel = await db.get(ChannelConfig, int(channel_id))
        if channel is None or (channel.project_id and channel.project_id != task.project_id):
            raise HTTPException(status_code=422, detail={"code": "webhook_result_channel_invalid",
                                                         "message": "Choose a channel of this Workspace."})
        config["output_channel_id"] = channel.id
    task.config = config


async def list_webhooks(db: AsyncSession) -> list[dict[str, Any]]:
    webhooks = (await db.execute(select(Webhook).order_by(Webhook.name))).scalars().all()
    return [await serialize_webhook(db, webhook) for webhook in webhooks]


async def create_webhook(db: AsyncSession, *, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()
    if not name or not project_id:
        raise HTTPException(status_code=400, detail="name and project_id are required")
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    agent_type = await _agent_mode(db, payload)
    webhook = Webhook(
        id=str(uuid.uuid4()),
        project_id=project_id,
        owner_id=user_id,
        name=name,
        description=str(payload.get("description") or "").strip() or None,
        source_type=_source(payload.get("source_type")),
        is_active=bool(payload.get("is_active", True)),
        task_id=await _action(db, payload.get("task_id"), project_id),
        alert_filter=_alert_filter(payload.get("alert_filter")),
        group_window_minutes=30 if payload.get("group_window_minutes") is None else int(payload["group_window_minutes"]),
        rate_limit_per_hour=_rate_limit(payload.get("rate_limit_per_hour"), 20),
        poll_query=str(payload.get("poll_query") or "").strip() or None,
        accept_untimestamped=_untimestamped(payload),
    )
    if agent_type is not None:
        webhook.agent_type = agent_type
    db.add(webhook)
    await db.flush()
    if "result_channel_id" in payload and webhook.task_id:
        await _set_result_channel(db, webhook.task_id, payload.get("result_channel_id"))
    raw_secret = await issue_webhook_secret(db, webhook)
    await db.commit()
    return {**await serialize_webhook(db, webhook), "secret": raw_secret}


async def update_webhook(db: AsyncSession, *, webhook_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    webhook = await _load(db, webhook_id)
    agent_type = await _agent_mode(db, payload)
    if agent_type is not None:
        webhook.agent_type = agent_type
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        webhook.name = name
    if "project_id" in payload:
        project_id = str(payload.get("project_id") or "").strip()
        if not project_id or not await db.get(Project, project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        webhook.project_id = project_id
    if "description" in payload:
        webhook.description = str(payload.get("description") or "").strip() or None
    if "source_type" in payload:
        webhook.source_type = _source(payload.get("source_type"))
    if "task_id" in payload:
        webhook.task_id = await _action(db, payload.get("task_id"), webhook.project_id)
    elif "project_id" in payload and webhook.task_id:
        # A move to another Workspace keeps the Action only when it lives there too.
        task = await db.get(Task, webhook.task_id)
        if task is None or task.project_id != webhook.project_id:
            webhook.task_id = None
    if "alert_filter" in payload:
        webhook.alert_filter = _alert_filter(payload.get("alert_filter"))
    if payload.get("group_window_minutes") is not None:
        webhook.group_window_minutes = int(payload["group_window_minutes"])
    if payload.get("rate_limit_per_hour") is not None:
        webhook.rate_limit_per_hour = _rate_limit(payload["rate_limit_per_hour"], webhook.rate_limit_per_hour or 20)
    if payload.get("accept_untimestamped") is not None or webhook.source_type in HOST_SIGNED_SOURCES:
        webhook.accept_untimestamped = _untimestamped({**payload, "source_type": webhook.source_type})
    if "poll_query" in payload and payload.get("poll_query") is not None:
        webhook.poll_query = str(payload.get("poll_query") or "").strip() or None
    if payload.get("is_active") is not None:
        webhook.is_active = bool(payload.get("is_active"))
    await db.commit()
    await db.refresh(webhook)
    return await serialize_webhook(db, webhook)


async def rotate_webhook_secret(db: AsyncSession, *, webhook_id: str, user_id: str | None = None) -> dict[str, Any]:
    """A new secret, returned once; audited with the webhook's id and name, never the secret."""
    webhook = await _load(db, webhook_id)
    raw_secret = await issue_webhook_secret(db, webhook)
    db.add(AuditLog(user_id=user_id, action="webhook.secret_rotated", resource_type="webhook", resource_id=webhook.id,
                    details={"name": webhook.name}))
    await db.commit()
    return {**await serialize_webhook(db, webhook), "secret": raw_secret}


async def send_test_alert(db: AsyncSession, *, webhook_id: str, sample: str, scheduler: Any = None) -> dict[str, Any]:
    webhook = await _load(db, webhook_id)
    payload = sample_payload(webhook.source_type or "generic", sample)
    if payload is None:
        raise HTTPException(status_code=422, detail={"code": "webhook_sample_unknown",
                                                     "message": "Choose one of the listed samples."})
    # The test goes through the real signature check: signed like a sender would sign it (timestamp + body).
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    secret = await resolve_webhook_secret(db, webhook)
    headers = {
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": sign_timestamped(secret or "", timestamp, body),
        "X-Webhook-Delivery": f"test-{uuid.uuid4()}",
    }
    return await receive_alert(db, webhook=webhook, body=body, headers=headers, is_test=True, scheduler=scheduler)


async def list_webhook_events(db: AsyncSession, *, webhook_id: str | None = None, limit: int = 20) -> list[dict]:
    if webhook_id:
        await _load(db, webhook_id)
    return await list_events(db, webhook_id=webhook_id, limit=limit)


async def delete_webhook(db: AsyncSession, *, webhook_id: str) -> dict[str, Any]:
    webhook = await _load(db, webhook_id)
    from ....models.integration.webhook import WebhookDeliveryKey, WebhookEvent

    await db.execute(sa_delete(WebhookDeliveryKey).where(WebhookDeliveryKey.webhook_id == webhook_id))
    for event in (await db.execute(select(WebhookEvent).where(WebhookEvent.webhook_id == webhook_id))).scalars():
        await db.delete(event)
    await db.delete(webhook)
    await db.commit()
    return {"status": "deleted"}
