"""Server-side chat search: title or first user message.

One clause for the list, the counts and the bulk scopes, so "Select all 3 matching" covers exactly the
chats the search shows. LIKE wildcards in the query are literal.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select

from ...models import Message
from ...models import Session as AgentSession


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def thread_search_clause(query: str) -> Any | None:
    """Title or first user message contains ``query`` (case-insensitive, LIKE wildcards escaped)."""
    normalized = str(query or "").strip()
    if not normalized:
        return None
    pattern = f"%{_escape_like(normalized)}%"
    first_user_message = (
        select(Message.content)
        .where(Message.session_id == AgentSession.id, Message.role == "user")
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(1)
        .correlate(AgentSession)
        .scalar_subquery()
    )
    return or_(
        AgentSession.metadata_["title"].as_string().ilike(pattern, escape="\\"),
        first_user_message.ilike(pattern, escape="\\"),
    )


__all__ = ["thread_search_clause"]
