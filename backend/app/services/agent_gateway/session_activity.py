"""What an open octryx-claude session is doing, for the person's phone (Octryx Mobile).

The activity comes from the calls the session makes anyway:

- a tool check: ``working``; one Claude Code asks the person about (``ask``): ``approval``;
- a finished tool: ``working``;
- the Stop hook (verification): ``waiting``, with the last answer and the session's title, which the client reads
  from its transcript and redacts like the session digest before it sends them;
- the launcher's heartbeat (every 30 s while Claude Code runs) keeps the session listed; a session that sends
  none for :data:`OPEN_FOR` is no longer open (the terminal was closed without a clean end).

:func:`open_sessions` lists the person's own open sessions; it never returns another user's row.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, Project, Session, UserDevice
from ...time_utils import utc_now
from .engine_keys import ENGINE_CLAUDE_CODE, ENGINES, SESSION_ENGINE_KEY
from .presence import session_key_hash

ACTIVITY_WORKING = "working"
ACTIVITY_APPROVAL = "approval"
ACTIVITY_WAITING = "waiting"
ACTIVITIES = (ACTIVITY_WORKING, ACTIVITY_APPROVAL, ACTIVITY_WAITING)
OPEN_FOR = timedelta(minutes=2)
MAX_TITLE = 200
MAX_LAST_TEXT = 4000


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned[:limit] or None


async def note_activity(db: AsyncSession, session_key: str, activity: str, *, title: object = None,
                        last_text: object = None) -> None:
    """Record the session's activity (and, from the Stop hook, its title and last answer). Flushes."""
    if activity not in ACTIVITIES:
        return
    row = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))).scalar_one_or_none()
    if row is None or row.stopped_at is not None:
        return
    row.activity, row.activity_at = activity, utc_now()
    if not row.title and (clean := _text(title, MAX_TITLE)):
        row.title = clean
    if (answer := _text(last_text, MAX_LAST_TEXT)) is not None:
        row.last_text = answer
    await db.flush()


async def note_heartbeat(db: AsyncSession, session_key: str, *, user_id: str) -> None:
    """The launcher is alive: move ``heartbeat_at`` of the caller's own open presence. Flushes."""
    row = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))).scalar_one_or_none()
    if row is None or row.stopped_at is not None or row.user_id != user_id:
        return
    row.heartbeat_at = utc_now()
    await db.flush()


def _iso(value: Any) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


async def session_engines(db: AsyncSession, session_ids: set[str]) -> dict[str, str]:
    """The engine each gateway session's launcher registered (``sessions.metadata.engine``). The launcher sends
    ``engine`` only for Codex (``cli_session.register``), so a session without one is Claude Code."""
    if not session_ids:
        return {}
    rows = (await db.execute(select(Session.id, Session.metadata_).where(Session.id.in_(session_ids)))).all()
    engines: dict[str, str] = {}
    for session_id, metadata in rows:
        engine = (metadata or {}).get(SESSION_ENGINE_KEY) if isinstance(metadata, dict) else None
        engines[str(session_id)] = engine if engine in ENGINES else ENGINE_CLAUDE_CODE
    return engines


async def open_sessions(db: AsyncSession, *, user_id: str) -> list[dict[str, Any]]:
    """The person's own octryx-claude sessions that are open now (a heartbeat or a call within :data:`OPEN_FOR`)."""
    since = utc_now() - OPEN_FOR
    seen = func.coalesce(AgentPresence.heartbeat_at, AgentPresence.last_seen_at)
    rows = (
        await db.execute(
            select(AgentPresence)
            .where(AgentPresence.user_id == user_id, AgentPresence.stopped_at.is_(None),
                   or_(AgentPresence.heartbeat_at >= since, AgentPresence.last_seen_at >= since))
            .order_by(seen.desc())
            .limit(50)
        )
    ).scalars().all()
    projects = {row.id: row.name for row in (await db.execute(
        select(Project).where(Project.id.in_({row.project_id for row in rows})))).scalars()} if rows else {}
    device_ids = {row.device_id for row in rows if row.device_id}
    devices = {row.id: row.name for row in (await db.execute(
        select(UserDevice).where(UserDevice.id.in_(device_ids), UserDevice.owner_user_id == user_id))).scalars()
    } if device_ids else {}
    engines = await session_engines(db, {row.session_id for row in rows if row.session_id})
    return [
        {
            "id": session_key_hash(row.session_key),
            "title": row.title or (f"{row.work_item_key}" if row.work_item_key else None),
            "workspace": {"id": row.project_id, "name": projects.get(row.project_id, "")},
            "device": devices.get(row.device_id or "", None),
            "profile": row.profile,
            # The coding engine the launcher registered the session with (Claude Code or Codex, ``session_engines``).
            "engine": engines.get(row.session_id or "", ENGINE_CLAUDE_CODE),
            "activity": row.activity or ACTIVITY_WORKING,
            "activity_at": _iso(row.activity_at),
            "last_text": row.last_text,
            "branch": row.branch,
            "work_item": row.work_item_key,
            "model": row.model,
            "started_at": _iso(row.registered_at),
            "last_seen_at": _iso(row.last_seen_at),
        }
        for row in rows
    ]


__all__ = ["ACTIVITIES", "ACTIVITY_APPROVAL", "ACTIVITY_WAITING", "ACTIVITY_WORKING", "OPEN_FOR", "note_activity",
           "note_heartbeat", "open_sessions", "session_engines"]
