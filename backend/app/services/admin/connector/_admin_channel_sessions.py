"""Read views of channel conversation sessions and Teams call sessions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Message, Project, Session


def _serialize_channel_session(row: tuple[Session, str | None, int, Any]) -> dict[str, Any]:
    session, project_name, message_count, last_message_at = row
    meta = session.metadata_ or {}
    return {
        "id": session.id,
        "status": session.status,
        "project_id": session.project_id,
        "project_name": project_name,
        "agent_type": session.agent_type,
        "title": meta.get("title") or meta.get("channel_name") or "Channel thread",
        "channel": meta.get("channel"),
        "channel_id": meta.get("channel_id"),
        "channel_name": meta.get("channel_name"),
        "channel_key": meta.get("channel_key"),
        "conversation_id": meta.get("conversation_id"),
        "channel_type": meta.get("channel_type"),
        "sender_id": meta.get("sender_id"),
        "message_count": int(message_count or 0),
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "last_message_at": last_message_at.isoformat() if last_message_at else None,
    }


async def list_channel_sessions(db: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit or 50), 200))
    result = await db.execute(
        select(
            Session,
            Project.name.label("project_name"),
            func.count(Message.id).label("message_count"),
            func.max(Message.created_at).label("last_message_at"),
        )
        .outerjoin(Project, Project.id == Session.project_id)
        .outerjoin(Message, Message.session_id == Session.id)
        .where(Session.metadata_["channel_session"].as_boolean() == true())
        .group_by(Session.id, Project.name)
        .order_by(Session.started_at.desc())
        .limit(bounded_limit)
    )
    return [_serialize_channel_session(row) for row in result.all()]


async def list_call_sessions(db: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent Teams voice call sessions with per-turn stats and status."""
    bounded_limit = max(1, min(int(limit or 50), 200))
    result = await db.execute(
        select(
            Session,
            Project.name.label("project_name"),
            func.count(Message.id).label("message_count"),
            func.max(Message.created_at).label("last_message_at"),
        )
        .outerjoin(Project, Project.id == Session.project_id)
        .outerjoin(Message, Message.session_id == Session.id)
        .where(Session.agent_type == "teams_call")
        .group_by(Session.id, Project.name)
        .order_by(Session.started_at.desc())
        .limit(bounded_limit)
    )
    rows = result.all()
    out = []
    for session, project_name, message_count, last_message_at in rows:
        meta = session.metadata_ or {}
        turns = int(message_count or 0) // 2  # each turn = 1 user + 1 assistant message
        out.append({
            "id": session.id,
            "call_id": meta.get("call_id", ""),
            "channel_id": meta.get("channel_id", ""),
            "project_id": session.project_id,
            "project_name": project_name or "",
            "status": session.status,
            "turns": turns,
            "message_count": int(message_count or 0),
            "last_error": meta.get("last_error"),
            "stt_provider": meta.get("stt_provider"),
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "last_activity_at": last_message_at.isoformat() if last_message_at else None,
        })
    return out
