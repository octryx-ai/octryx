"""Octryx Mobile "live": the owner talks to Claude Code sessions running on their own device.

The device service (``octryx-claude device live on``, off by default) reports the sessions it sees and relays the
owner's texts to their inboxes (``clients/octryx-claude/octryx_claude/live_bridge.py``). Here:

- **from the device** (channel messages, :func:`handle_device_message`): ``live_sessions`` replaces the device's
  snapshot; ``live_incoming`` stores what a session answered; ``live_delivery`` settles an outgoing message.
- **to the device** (:func:`deliver_pending`, every channel tick): pending outgoing messages go out as
  ``live_send``; one the device has not settled after :data:`SENT_TIMEOUT` is ``failed`` (``no_answer``).
- **pictures** (screenshots from the phone): at most :data:`MAX_IMAGES` PNG, JPEG or
  WebP pictures of at most :data:`MAX_IMAGE_BYTES` each ride with a message (checked by their bytes, not their name).
  They go to the device as ``live_attachment`` chunks before the ``live_send``, and are deleted as soon as the device
  settles the message; the device keeps them in its own state folder (0600) and gives the session the path.
- **the owner** (:func:`queue_message`, :func:`overview`, :func:`conversation`): only the device's owner, only
  to a session the device lists right now and reported within :data:`FRESH_FOR`, at most :data:`MAX_TEXT`
  characters, :data:`MAX_PER_MINUTE` per minute and :data:`MAX_OPEN` not yet settled per device. The routes
  refuse API keys and bearer tokens: only the person's own web or phone login sends (a text to a session in
  bypass mode can make it act on the machine).

Nobody else reads either table: there is no admin route. Messages older than :data:`KEEP_DAYS` are deleted.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceLiveSnapshot, LiveAttachment, LiveMessage, LocalClaudeSession, User, UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE
from ...models.security.live import LIVE_OUT
from ...time_utils import utc_now
from .live_values import FRESH_FOR, IMAGE_TEXT, MAX_OPEN, MAX_PER_MINUTE, MAX_TEXT, PEER, LiveError, decode_images

# --- the owner ---------------------------------------------------------------------------------------------------


async def _own_device(db: AsyncSession, user: User, device_id: str) -> UserDevice:
    device = await db.get(UserDevice, device_id)
    if device is None or device.owner_user_id != user.id or device.status != DEVICE_STATUS_ACTIVE:
        raise LiveError("device_not_found", 404)
    return device


def _fresh(snapshot: DeviceLiveSnapshot | None) -> bool:
    return snapshot is not None and snapshot.live == "on" and snapshot.reported_at >= utc_now() - FRESH_FOR


def _session_folder(snapshot: DeviceLiveSnapshot | None, peer: str) -> tuple[str, str]:
    for item in (snapshot.sessions if snapshot else []) or []:
        if item.get("peer") == peer:
            return f"live:{item.get('profile') or 'default'}", str(item.get("cwd") or "")
    return "live", ""


async def _dispatch_allowed(db: AsyncSession, device: UserDevice, *, user_id: str, peer: str,
                            snapshot: DeviceLiveSnapshot | None) -> str:
    """The platform's kill switch and the device's pause stop live texts like every device run,
    and each one is a recorded dispatch decision. ``""`` when it may go, else the refusal reason."""
    from ..decisions.devices import record_device_dispatch  # noqa: PLC0415
    from .dispatch_gate import DispatchDecision  # noqa: PLC0415
    from .platform_switch import device_runs_platform_enabled  # noqa: PLC0415

    profile, folder = _session_folder(snapshot, peer)
    reason = ""
    if not await device_runs_platform_enabled(db):
        reason = "device_runs_platform_disabled"
    elif device.paused:
        reason = "device_paused"
    decision = DispatchDecision.deny("denied", reason) if reason else DispatchDecision(True)
    record_device_dispatch(decision, user_id=user_id, profile=profile, folder=folder, workspace_id=None,
                           session_id=None)
    return reason


async def queue_message(db: AsyncSession, user: User, *, device_id: str, peer: str, text: Any,
                        images: Any = None) -> LiveMessage:
    device = await _own_device(db, user, device_id)
    body = str(text or "").replace("\x00", "").strip() if isinstance(text, str) else ""
    pictures = decode_images(images)
    if pictures and not body:
        body = IMAGE_TEXT
    if not body or len(body) > MAX_TEXT:
        raise LiveError("text_invalid", 422)
    snapshot = await db.get(DeviceLiveSnapshot, device.id)
    if not _fresh(snapshot):
        raise LiveError("live_unavailable", 409)
    if peer not in {item.get("peer") for item in snapshot.sessions or []}:
        raise LiveError("session_not_running", 409)
    if reason := await _dispatch_allowed(db, device, user_id=user.id, peer=peer, snapshot=snapshot):
        raise LiveError(reason, 403)
    now = utc_now()
    sent = await db.scalar(select(func.count()).select_from(LiveMessage).where(
        LiveMessage.owner_user_id == user.id, LiveMessage.direction == LIVE_OUT,
        LiveMessage.created_at >= now - timedelta(minutes=1)))
    if int(sent or 0) >= MAX_PER_MINUTE:
        raise LiveError("rate_limited", 429)
    unsettled = await db.scalar(select(func.count()).select_from(LiveMessage).where(
        LiveMessage.device_id == device.id, LiveMessage.direction == LIVE_OUT,
        LiveMessage.state.in_(("pending", "sent"))))
    if int(unsettled or 0) >= MAX_OPEN:
        raise LiveError("too_many_open", 429)
    message = LiveMessage(owner_user_id=user.id, device_id=device.id, peer=peer, direction=LIVE_OUT,
                          text=body, state="pending", attachment_count=len(pictures), created_at=now, updated_at=now)
    db.add(message)
    await db.flush()
    for position, (media_type, data) in enumerate(pictures):
        db.add(LiveAttachment(message_id=message.id, position=position, media_type=media_type, size=len(data),
                              sha256=hashlib.sha256(data).hexdigest(), content=data, created_at=now))
    await db.flush()
    return message


async def fork_session(db: AsyncSession, user: User, *, device_id: str, peer: str, message: Any) -> dict[str, str]:
    """Continue a copy of a listed session from the phone (phase B): only the owner's device, only a
    session listed right now and idle (a fork beside a working session would be a second writer in its folder), and
    only one the device reported for take-over (the Mac's own opt-in per profile). The copy runs as a Mac chat whose
    every write step asks first; the original keeps running untouched."""
    from .local_sessions import LocalSessionError, take_over  # noqa: PLC0415

    device = await _own_device(db, user, device_id)
    snapshot = await db.get(DeviceLiveSnapshot, device.id)
    session = next((item for item in (snapshot.sessions if snapshot else []) or [] if item.get("peer") == peer), None)
    if not PEER.match(peer or "") or session is None or not _fresh(snapshot):
        raise LiveError("session_not_running", 409)
    if session.get("status") == "busy":
        raise LiveError("session_busy", 409)
    local = (await db.execute(select(LocalClaudeSession).where(
        LocalClaudeSession.device_id == device.id, LocalClaudeSession.owner_user_id == user.id,
        LocalClaudeSession.claude_session_id == str(session.get("session_id") or "")))).scalars().first()
    if local is None:
        raise LiveError("takeover_not_allowed_on_device", 409)
    try:
        return await take_over(db, user=user, local_id=local.id, prompt=message if isinstance(message, str) else "",
                               fork=True, fork_label=str(session.get("name") or ""))
    except LocalSessionError as error:
        raise LiveError(error.reason, error.status) from None


def serialize_message(message: LiveMessage) -> dict[str, Any]:
    return {"id": message.id, "device_id": message.device_id, "peer": message.peer, "direction": message.direction,
            "name": message.name or "", "text": message.text, "state": message.state, "reason": message.reason or "",
            "attachments": int(message.attachment_count or 0),
            "created_at": message.created_at.isoformat() + "Z" if message.created_at else None}


async def overview(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    """The owner's devices with live on: their running sessions, each with its last message."""
    rows = (await db.execute(select(DeviceLiveSnapshot, UserDevice).join(
        UserDevice, UserDevice.id == DeviceLiveSnapshot.device_id).where(
        DeviceLiveSnapshot.owner_user_id == user.id, UserDevice.owner_user_id == user.id,
        UserDevice.status == DEVICE_STATUS_ACTIVE))).all()
    out = []
    for snapshot, device in rows:
        if snapshot.live != "on":
            continue
        last: dict[str, LiveMessage] = {}
        messages = (await db.execute(select(LiveMessage).where(
            LiveMessage.owner_user_id == user.id, LiveMessage.device_id == device.id).order_by(
            LiveMessage.created_at.desc()).limit(200))).scalars().all()
        for message in messages:
            last.setdefault(message.peer, message)
        sessions = [{**item, "last_message": serialize_message(last[item["peer"]]) if item["peer"] in last else None}
                    for item in snapshot.sessions or []]
        out.append({"device_id": device.id, "device_name": device.name, "fresh": _fresh(snapshot),
                    "reported_at": snapshot.reported_at.isoformat() + "Z", "sessions": sessions})
    return out


async def conversation(db: AsyncSession, user: User, *, device_id: str, peer: str,
                       limit: int = 200) -> dict[str, Any]:
    device = await _own_device(db, user, device_id)
    if not PEER.match(peer or ""):
        raise LiveError("session_not_found", 404)
    messages = (await db.execute(select(LiveMessage).where(
        LiveMessage.owner_user_id == user.id, LiveMessage.device_id == device.id, LiveMessage.peer == peer).order_by(
        LiveMessage.created_at.desc()).limit(max(1, min(limit, 500))))).scalars().all()
    snapshot = await db.get(DeviceLiveSnapshot, device.id)
    session = next((item for item in (snapshot.sessions if snapshot else []) or [] if item.get("peer") == peer), None)
    running = bool(session and _fresh(snapshot))
    return {"device_id": device.id, "device_name": device.name, "peer": peer, "running": running,
            "session": session, "items": [serialize_message(message) for message in reversed(messages)]}


__all__ = [
    "conversation",
    "overview",
    "queue_message",
    "serialize_message",
]
