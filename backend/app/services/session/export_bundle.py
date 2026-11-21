"""Shared data loading for session exports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, ToolCall, TurnTrace, User
from .collaboration import require_session_access

MAX_FILENAME_CHARS = 90


@dataclass(frozen=True, slots=True)
class SessionExportBundle:
    session: Any
    access_role: str
    messages: list[Message]
    tool_calls: list[ToolCall]
    turn_traces: list[TurnTrace]
    exported_at: str
    exported_by: User | None


async def load_session_export_bundle(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    exported_by: User | None,
) -> SessionExportBundle:
    session, access_role = await require_session_access(db, session_id=session_id, user_id=user_id)
    messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        )
        .scalars()
        .all()
    )
    tool_calls = (
        (
            await db.execute(
                select(ToolCall)
                .where(ToolCall.session_id == session.id)
                .order_by(ToolCall.created_at.asc(), ToolCall.id.asc())
            )
        )
        .scalars()
        .all()
    )
    turn_traces = (
        (
            await db.execute(
                select(TurnTrace)
                .where(TurnTrace.session_id == session.id)
                .order_by(TurnTrace.created_at.asc(), TurnTrace.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return SessionExportBundle(
        session=session,
        access_role=access_role,
        messages=list(messages),
        tool_calls=list(tool_calls),
        turn_traces=list(turn_traces),
        exported_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        exported_by=exported_by,
    )


def session_export_title(session: Any, *, fallback: str) -> str:
    return str((session.metadata_ or {}).get("title") or fallback).strip() or fallback


def session_export_filename(*, title: str, session_id: str, suffix: str) -> str:
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", title.strip()).strip("-.")
    if not safe_title:
        safe_title = "chat-evidence"
    return f"{safe_title[:MAX_FILENAME_CHARS]}-{session_id[:8]}.{suffix}"


def exporter_label(user: User | None) -> str:
    return str(getattr(user, "email", None) or getattr(user, "username", None) or "unknown")


def user_export_payload(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
    }
