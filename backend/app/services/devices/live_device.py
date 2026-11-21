"""Octryx Mobile "live", the device side: its channel messages and the tick that delivers pending texts
(``devices.live``)."""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceLiveSnapshot, LiveAttachment, LiveMessage, User, UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE
from ...models.security.live import LIVE_IN, LIVE_OUT
from ...time_utils import utc_now
from .live_values import (
    CHUNK_BYTES,
    DELIVERY_REASONS,
    KEEP_DAYS,
    MAX_INCOMING_PER_MINUTE,
    MAX_TEXT,
    PEER,
    SENT_TIMEOUT,
    SETTLED,
    _text,
    normalize_sessions,
)


async def handle_device_message(db: AsyncSession, device: UserDevice, message_type: str,
                                body: dict[str, Any]) -> None:
    if message_type == "live_sessions":
        await _record_snapshot(db, device, body)
    elif message_type == "live_incoming":
        await _record_incoming(db, device, body)
    elif message_type == "live_delivery":
        await _record_delivery(db, device, body)
    elif message_type == "live_progress":
        from .live_progress import record_progress  # noqa: PLC0415 - it imports this module

        await record_progress(db, device, body)


async def _record_snapshot(db: AsyncSession, device: UserDevice, body: dict[str, Any]) -> None:
    snapshot = await db.get(DeviceLiveSnapshot, device.id)
    if snapshot is None:
        snapshot = DeviceLiveSnapshot(device_id=device.id, owner_user_id=device.owner_user_id)
        db.add(snapshot)
    live = body.get("live") is not False
    snapshot.sessions = normalize_sessions(body.get("sessions")) if live else []
    snapshot.live = "on" if live else "off"
    snapshot.reported_at = utc_now()
    await db.execute(delete(LiveMessage).where(LiveMessage.device_id == device.id,
                                               LiveMessage.created_at < utc_now() - timedelta(days=KEEP_DAYS)))
    await db.flush()


async def _record_incoming(db: AsyncSession, device: UserDevice, body: dict[str, Any]) -> None:
    peer, text = _text(body.get("from"), 300), _text(body.get("text"), MAX_TEXT).strip()
    if not PEER.match(peer) or not text:
        return
    recent = await db.scalar(select(func.count()).select_from(LiveMessage).where(
        LiveMessage.device_id == device.id, LiveMessage.direction == LIVE_IN,
        LiveMessage.created_at >= utc_now() - timedelta(minutes=1)))
    if int(recent or 0) >= MAX_INCOMING_PER_MINUTE:
        return  # a session that floods the relay does not flood the phone
    now = utc_now()
    db.add(LiveMessage(owner_user_id=device.owner_user_id, device_id=device.id, peer=peer, direction=LIVE_IN,
                       name=_text(body.get("name"), 120) or None, text=text, state="received", created_at=now,
                       updated_at=now))
    await db.flush()


async def _drop_attachments(db: AsyncSession, message_id: str) -> None:
    """A settled message keeps no picture on the platform (the device has its copy, or it failed)."""
    await db.execute(delete(LiveAttachment).where(LiveAttachment.message_id == message_id))


async def _record_delivery(db: AsyncSession, device: UserDevice, body: dict[str, Any]) -> None:
    message = await db.get(LiveMessage, _text(body.get("message_id"), 40))
    state = _text(body.get("state"), 20)
    if message is None or message.device_id != device.id or message.direction != LIVE_OUT or state not in SETTLED:
        return
    reason = _text(body.get("reason"), 60)
    message.state = state
    message.reason = reason if reason in DELIVERY_REASONS and reason else None
    message.updated_at = utc_now()
    await _drop_attachments(db, message.id)
    await db.flush()


async def deliver_pending(db: AsyncSession, connection: Any) -> None:
    """One channel tick: pending messages go to the device; unsettled ones time out."""
    now = utc_now()
    rows = (await db.execute(select(LiveMessage).where(
        LiveMessage.device_id == connection.device_id, LiveMessage.direction == LIVE_OUT,
        LiveMessage.state.in_(("pending", "sent"))).order_by(LiveMessage.created_at))).scalars().all()
    if not rows:
        return
    from .platform_switch import device_runs_platform_enabled  # noqa: PLC0415

    device = await db.get(UserDevice, connection.device_id)
    # Switched off or paused after the text was queued: it never leaves.
    stopped = ("device_runs_platform_disabled" if not await device_runs_platform_enabled(db)
               else "device_paused" if device is None or device.paused or device.status != DEVICE_STATUS_ACTIVE
               else "")
    sender = ""
    for message in rows:
        if message.state == "sent":
            if message.updated_at < now - SENT_TIMEOUT:
                message.state, message.reason, message.updated_at = "failed", "no_answer", now
                await _drop_attachments(db, message.id)
            continue
        if stopped:
            message.state, message.reason, message.updated_at = "failed", stopped, now
            await _drop_attachments(db, message.id)
            continue
        if not sender:
            user = await db.get(User, message.owner_user_id)
            sender = (user.display_name or user.username) if user is not None else "the owner"
        body = {"message_id": message.id, "peer": message.peer, "text": message.text, "sender": sender}
        if message.attachment_count:  # only then: a device service that does not know the key never sees it
            body["attachments"] = await _send_attachments(db, connection, message)
        await connection.send("live_send", body)
        message.state, message.updated_at = "sent", now
    await db.flush()


async def _send_attachments(db: AsyncSession, connection: Any, message: LiveMessage) -> list[dict[str, Any]]:
    """The message's pictures as ``live_attachment`` chunks; returns what the ``live_send`` then names
    (id, type, size, hash)."""
    rows = (await db.execute(select(LiveAttachment).where(LiveAttachment.message_id == message.id)
                             .order_by(LiveAttachment.position))).scalars().all()
    named = []
    for row in rows:
        content = bytes(row.content)
        total = max(1, -(-len(content) // CHUNK_BYTES))
        for index in range(total):
            chunk = content[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]
            await connection.send("live_attachment", {"message_id": message.id, "attachment_id": row.id,
                                                      "index": index, "total": total,
                                                      "data": base64.b64encode(chunk).decode()})
        named.append({"id": row.id, "media_type": row.media_type, "size": row.size, "sha256": row.sha256})
    return named

