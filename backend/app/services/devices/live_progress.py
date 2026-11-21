"""What a running Claude Code session is doing, for its owner's phone, which otherwise
sees only the session's answers. Phase A: the device reads the session's own transcript (read-only,
``clients/octryx-claude/octryx_claude/live_progress.py``) and sends short events as ``live_progress {peer, events}``.

- **from the device** (:func:`record_progress`): only for a session the device lists right now (the same rule as a
  live message); every event normalized again here (a closed set of kinds and fields, every text clipped and
  redacted once more), at most :data:`MAX_EVENTS_PER_MESSAGE` per message and :data:`MAX_EVENTS_PER_MINUTE` per device;
  each gets the next ``seq`` of its session. Per session the newest :data:`KEEP_PER_SESSION` are kept, nothing older
  than :data:`KEEP_DAYS`.
- **the owner** (:func:`progress`): ``since_seq`` answers only what is newer, so the phone catches up after it was away;
  only the device's owner, only by their interactive login (the route), only a session listed right now.

Nobody else reads the table: there is no admin route.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceLiveSnapshot, LiveProgressEvent, User, UserDevice
from ...time_utils import utc_now
from ..knowledge.memory.session_lessons import redact
from .live import _fresh, _own_device
from .live_values import PEER, LiveError

KINDS = frozenset({"text", "tool", "result", "prompt", "compact"})
FIELDS = {"text": 600, "tool": 60, "input": 160, "line": 160, "from": 60, "id": 80, "at": 40}
MAX_EVENTS_PER_MESSAGE = 50
MAX_EVENTS_PER_MINUTE = 600
KEEP_PER_SESSION = 500
KEEP_DAYS = 7
PAGE = 200


def normalize_event(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    event: dict[str, Any] = {"kind": raw["kind"]}
    for field, limit in FIELDS.items():
        value = raw.get(field)
        if isinstance(value, str) and value:
            text = value.replace("\x00", "")[:limit]
            event[field] = text if field in ("id", "at") else redact(text)
    if raw["kind"] == "result":
        event["ok"] = raw.get("ok") is not False
    return event


async def record_progress(db: AsyncSession, device: UserDevice, body: dict[str, Any]) -> None:
    peer = str(body.get("peer") or "")[:300]
    events = [event for event in map(normalize_event, (body.get("events") or [])[:MAX_EVENTS_PER_MESSAGE]
                                     if isinstance(body.get("events"), list) else []) if event]
    if not events or not PEER.match(peer):
        return
    snapshot = await db.get(DeviceLiveSnapshot, device.id)
    if not _fresh(snapshot) or peer not in {item.get("peer") for item in snapshot.sessions or []}:
        return  # only a session the device lists right now
    now = utc_now()
    recent = await db.scalar(select(func.count()).select_from(LiveProgressEvent).where(
        LiveProgressEvent.device_id == device.id, LiveProgressEvent.created_at >= now - timedelta(minutes=1)))
    room = MAX_EVENTS_PER_MINUTE - int(recent or 0)
    if room <= 0:
        return
    last = await db.scalar(select(func.max(LiveProgressEvent.seq)).where(
        LiveProgressEvent.device_id == device.id, LiveProgressEvent.peer == peer))
    seq = int(last or 0)
    for event in events[:room]:
        seq += 1
        db.add(LiveProgressEvent(device_id=device.id, owner_user_id=device.owner_user_id, peer=peer, seq=seq,
                                 kind=event["kind"], body=event, created_at=now))
    await db.flush()
    await db.execute(delete(LiveProgressEvent).where(
        LiveProgressEvent.device_id == device.id, LiveProgressEvent.peer == peer,
        LiveProgressEvent.seq <= seq - KEEP_PER_SESSION))
    await db.execute(delete(LiveProgressEvent).where(
        LiveProgressEvent.device_id == device.id, LiveProgressEvent.created_at < now - timedelta(days=KEEP_DAYS)))


async def progress(db: AsyncSession, user: User, *, device_id: str, peer: str, since_seq: int = 0) -> dict[str, Any]:
    device = await _own_device(db, user, device_id)
    snapshot = await db.get(DeviceLiveSnapshot, device.id)
    session = next((item for item in (snapshot.sessions if snapshot else []) or [] if item.get("peer") == peer), None)
    if not PEER.match(peer or "") or session is None:
        raise LiveError("session_not_running", 409)
    rows = (await db.execute(select(LiveProgressEvent).where(
        LiveProgressEvent.device_id == device.id, LiveProgressEvent.owner_user_id == user.id,
        LiveProgressEvent.peer == peer, LiveProgressEvent.seq > max(0, since_seq))
        .order_by(LiveProgressEvent.seq).limit(PAGE + 1))).scalars().all()
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    last = await db.scalar(select(func.max(LiveProgressEvent.seq)).where(
        LiveProgressEvent.device_id == device.id, LiveProgressEvent.peer == peer))
    return {
        "peer": peer,
        "running": _fresh(snapshot),
        "status": str(session.get("status") or ""),
        "events": [{**(row.body or {}), "seq": row.seq} for row in rows],
        "last_seq": int(last or 0),
        "more": more,
    }


__all__ = ["KEEP_PER_SESSION", "MAX_EVENTS_PER_MESSAGE", "normalize_event", "progress", "record_progress"]
