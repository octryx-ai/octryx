"""The sticky content state of a coding-client conversation, for its user and its Workspace.

The gateway keys the sticky state by the gateway session and Claude Code's conversation id
(``conversation_state``); ``/clear`` starts a new id. The launcher's hooks send that id as ``session_id`` with
every call, so:

- :func:`note_conversation` keeps the conversation the client is in now on the gateway session
  (``metadata.content_conversation``; written only when it changes);
- :func:`route_answer` gives a hook the conversation's route once it is routed by a content policy (the
  launcher shows its one-time terminal notice from it);
- :func:`presence_sensitivity` gives the Agents area the state of each session's current conversation, so the
  badge clears after ``/clear``. A session whose client never reported a conversation shows its newest state.

Only names, counts, times and ids leave this module (categories, detector counts, policy, decision, route target);
the state never holds content.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ContentConversationState, Session
from .conversation_state import SESSION_WIDE, conversation_key
from .notices import decision_token, name_token

METADATA_KEY = "content_conversation"
MAX_ITEMS = 20


def hook_conversation(hook_body: Mapping[str, Any]) -> str:
    """The conversation a hook call belongs to (Claude Code's ``session_id``), or the whole session."""
    value = hook_body.get("session_id")
    return conversation_key({"x-claude-code-session-id": value if isinstance(value, str) else ""})


def note_conversation(session: Session, hook_body: Mapping[str, Any]) -> str:
    """Remember the client's current conversation on the gateway session (the caller commits)."""
    key = hook_conversation(hook_body)
    metadata = dict(session.metadata_ or {})
    if key != SESSION_WIDE and metadata.get(METADATA_KEY) != key:
        session.metadata_ = {**metadata, METADATA_KEY: key}
    return key


def _names(values: Iterable[Any]) -> list[str]:
    return sorted({value for value in values if name_token(value)})[:MAX_ITEMS]


def _counts(values: Any) -> dict[str, int]:
    items = values.items() if isinstance(values, Mapping) else ()
    return {name: count for name, count in sorted(items)[:MAX_ITEMS]
            if name_token(name) and type(count) is int and count > 0}


def _iso(value: Any) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


def state_payload(row: ContentConversationState) -> dict[str, Any]:
    return {
        "categories": _names(row.categories or ()),
        "detectors": _counts(row.detectors),
        "since": _iso(row.first_at),
        "policy_id": name_token(row.policy_id),
        "decision_id": decision_token(row.decision_id),
        "route_to": name_token(row.route_to),
    }


async def route_answer(db: AsyncSession, session_id: str, conversation: str) -> dict[str, Any]:
    """``{"content_route": ...}`` when the conversation is routed by a content policy, else ``{}``."""
    row = (await db.execute(select(ContentConversationState).where(
        ContentConversationState.session_id == session_id,
        ContentConversationState.conversation_key == conversation))).scalar_one_or_none()
    if row is None or not row.route_to:
        return {}
    return {"content_route": {**state_payload(row), "conversation": conversation}}


async def presence_sensitivity(db: AsyncSession, session_ids: Iterable[str | None]) -> dict[str, dict[str, Any]]:
    """The state of each session's current conversation (newest when none was reported); sessions without one
    are left out."""
    wanted = sorted({item for item in session_ids if item})
    if not wanted:
        return {}
    current = {row.id: (row.metadata_ or {}).get(METADATA_KEY) for row in (await db.execute(
        select(Session.id, Session.metadata_).where(Session.id.in_(wanted)))).all()}
    rows = (await db.execute(select(ContentConversationState).where(
        ContentConversationState.session_id.in_(wanted)).order_by(ContentConversationState.updated_at.asc())
    )).scalars()
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        reported = current.get(row.session_id)
        if reported and row.conversation_key != reported:
            continue
        payload = state_payload(row)
        if payload["categories"] or payload["route_to"]:
            found[row.session_id] = payload
    return found


__all__ = [
    "METADATA_KEY",
    "hook_conversation",
    "note_conversation",
    "presence_sensitivity",
    "route_answer",
    "state_payload",
]
