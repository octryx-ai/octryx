"""Admin management of outbound webhooks: list, create, update, delete."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import OutboundWebhook, OutboundWebhookDelivery, Project, User
from ...time_utils import utc_now
from ..outbound_egress import CONNECTION_OUTBOUND_WEBHOOK, connection_rule
from ..outbound_egress.target_check import check_connection_target
from ..outbound_url_policy import REASON_UNRESOLVABLE_HOST, OutboundURLPolicyError
from ..project.private_workspace import hidden_private_ids
from ..secret import encrypt_secret
from .catalog import _normalize_event_types
from .serialization import serialize_outbound_webhook, serialize_outbound_webhook_delivery


async def _require_admitted_url(url: str) -> None:
    try:
        await check_connection_target(url, connection_rule(CONNECTION_OUTBOUND_WEBHOOK))
    except OutboundURLPolicyError as refused:
        if refused.reason == REASON_UNRESOLVABLE_HOST:
            return
        raise HTTPException(status_code=400, detail=f"Outbound webhook URL refused: {refused.reason}") from None


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


async def _load(db: AsyncSession, webhook_id: str, viewer_id: str) -> OutboundWebhook:
    row = await db.get(OutboundWebhook, webhook_id)
    if row is None or row.project_id in await hidden_private_ids(db, viewer_id):
        raise HTTPException(status_code=404, detail="Outbound webhook not found")
    return row


async def list_outbound_webhooks(db: AsyncSession, *, viewer_id: str) -> list[dict[str, Any]]:
    hidden = await hidden_private_ids(db, viewer_id)
    rows = (
        (
            await db.execute(
                select(OutboundWebhook)
                .where(OutboundWebhook.project_id.is_(None) | OutboundWebhook.project_id.not_in(hidden))
                .order_by(
                    OutboundWebhook.name.asc(),
                    OutboundWebhook.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [serialize_outbound_webhook(row) for row in rows]


async def list_outbound_webhook_deliveries(
    db: AsyncSession,
    *,
    viewer_id: str,
    status_filter: str | None = None,
    webhook_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    hidden = await hidden_private_ids(db, viewer_id)
    hidden_webhooks = select(OutboundWebhook.id).where(OutboundWebhook.project_id.in_(hidden))
    stmt = (
        select(OutboundWebhookDelivery)
        .where(OutboundWebhookDelivery.project_id.is_(None) | OutboundWebhookDelivery.project_id.not_in(hidden),
               OutboundWebhookDelivery.webhook_id.not_in(hidden_webhooks))
        .order_by(OutboundWebhookDelivery.created_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    if status_filter:
        stmt = stmt.where(OutboundWebhookDelivery.status == str(status_filter).strip().lower())
    if webhook_id:
        stmt = stmt.where(OutboundWebhookDelivery.webhook_id == webhook_id)
    rows = (await db.execute(stmt)).scalars().all()
    names = dict((await db.execute(select(OutboundWebhook.id, OutboundWebhook.name))).all()) if rows else {}
    # Deliveries name their destination instead of a sliced id.
    return [{**serialize_outbound_webhook_delivery(row), "webhook_name": names.get(row.webhook_id)} for row in rows]


async def create_outbound_webhook(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    url = str(payload.get("url") or "").strip()
    project_id = str(payload.get("project_id") or "").strip() or None
    if not name or not url:
        raise HTTPException(status_code=422, detail="name and url are required")
    if project_id:
        project = await db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
    event_types = _normalize_event_types(payload.get("event_types") or [])
    await _require_admitted_url(url)
    secret = str(payload.get("secret") or "").strip() or secrets.token_urlsafe(32)
    row = OutboundWebhook(
        id=str(uuid.uuid4()),
        project_id=project_id,
        created_by=current_user.id,
        name=name,
        url=url,
        secret_hash=_hash_secret(secret),
        encrypted_secret=encrypt_secret(secret),
        is_active=bool(payload.get("is_active", True)),
    )
    row.event_types = event_types
    db.add(row)
    await db.commit()
    await db.refresh(row)
    serialized = serialize_outbound_webhook(row)
    serialized["signing_secret"] = secret
    return serialized


async def update_outbound_webhook(
    db: AsyncSession,
    *,
    webhook_id: str,
    viewer_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = await _load(db, webhook_id, viewer_id)
    if "name" in payload:
        row.name = str(payload.get("name") or "").strip()
    if "url" in payload:
        row.url = str(payload.get("url") or "").strip()
        if row.url:
            await _require_admitted_url(row.url)
    if "project_id" in payload:
        project_id = str(payload.get("project_id") or "").strip() or None
        if project_id:
            project = await db.get(Project, project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
        row.project_id = project_id
    if "event_types" in payload:
        row.event_types = _normalize_event_types(payload.get("event_types") or [])
    if "is_active" in payload:
        row.is_active = bool(payload.get("is_active"))
    rotated_secret = None
    if payload.get("rotate_secret"):
        rotated_secret = str(payload.get("secret") or "").strip() or secrets.token_urlsafe(32)
        row.secret_hash = _hash_secret(rotated_secret)
        row.encrypted_secret = encrypt_secret(rotated_secret)
    if not str(row.name or "").strip() or not str(row.url or "").strip():
        raise HTTPException(status_code=422, detail="name and url are required")
    row.updated_at = utc_now()
    await db.commit()
    await db.refresh(row)
    serialized = serialize_outbound_webhook(row)
    if rotated_secret:
        serialized["signing_secret"] = rotated_secret
    return serialized


async def delete_outbound_webhook(db: AsyncSession, *, webhook_id: str, viewer_id: str) -> dict[str, Any]:
    row = await _load(db, webhook_id, viewer_id)
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "id": webhook_id}
