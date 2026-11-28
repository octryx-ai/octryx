"""The conversation digest of a linked external CLI session, for the work-item handover context."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, Session
from ..mcp_external_session import EXTERNAL_AGENT_TYPE


async def linked_session_digest(
    db: AsyncSession,
    *,
    project_id: str | None,
    client_session_id: str,
    tail_chars: int,
) -> dict[str, str] | None:
    if not project_id or not client_session_id:
        return None
    session = (
        await db.execute(
            select(Session)
            .where(
                Session.agent_type == EXTERNAL_AGENT_TYPE,
                Session.project_id == project_id,
                Session.metadata_["client_session_id"].as_string() == client_session_id,
            )
            .order_by(Session.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if session is None:
        return None
    metadata: dict[str, Any] = dict(session.metadata_ or {})
    rows = (
        await db.execute(
            select(Message.role, Message.content)
            .where(Message.session_id == session.id)
            .order_by(Message.created_at.asc())
        )
    ).all()
    transcript = "\n\n".join(f"[{str(role or '').upper()}] {content or ''}" for role, content in rows)
    return {
        "summary": str(metadata.get("summary") or ""),
        "digest_tail": transcript[-max(0, int(tail_chars)) :] if tail_chars else "",
    }


__all__ = ["linked_session_digest"]
