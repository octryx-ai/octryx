"""Thread title and preview text of a chat session."""

from ...models import (
    Message,
)
from ...models import (
    Session as AgentSession,
)

__all__ = [
    "_session_title",
    "_session_preview",
    "_session_title_from_content",
    "_session_preview_from_content",
]


def _session_title(session: AgentSession, first_user_message: Message | None, fallback: str = "New thread") -> str:
    metadata = session.metadata_ or {}
    if metadata.get("title"):
        return str(metadata["title"])
    if first_user_message and first_user_message.content:
        return first_user_message.content[:80]
    return fallback


def _session_preview(last_message: Message | None, *, limit: int = 120) -> str:
    if not last_message or not last_message.content:
        return ""
    return last_message.content[:limit]


def _session_title_from_content(
    session: AgentSession,
    first_user_content: str | None,
    fallback: str = "New thread",
) -> str:
    metadata = session.metadata_ or {}
    if metadata.get("title"):
        return str(metadata["title"])
    content = str(first_user_content or "").strip()
    if content:
        return content[:80]
    return fallback


def _session_preview_from_content(last_message_content: str | None, *, limit: int = 120) -> str:
    content = str(last_message_content or "")
    if not content:
        return ""
    return content[:limit]
