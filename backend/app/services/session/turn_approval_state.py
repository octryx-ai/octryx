"""One owner for a chat turn paused at an approval.

Both session entry paths (``/api/v1/sessions/{id}/messages`` and ``/chat/api/send``)
mark the turn in flight with :func:`begin_chat_turn`. When a tool in that turn asks
for an approval, ``ensure_approval_request`` binds the new approval to the turn with
:func:`hold_turn_for_approval`. The binding lives under its own metadata key, so it
survives the end of the turn on either path, and the approval decision can resume
exactly the turn that asked for it with :func:`take_paused_turn`.

A binding is keyed by approval id inside the session's own metadata and is consumed
once. Grants stay one-shot and bound to ``(session, tool, request fingerprint)`` in
``services/tool_approval_gate.py``; this module only remembers *which turn* to resume
and *as whom*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, Message
from ...models import Session as AgentSession
from ...time_utils import utc_now_aware
from .collaboration import require_session_access

CURRENT_TURN_USER_MESSAGE_KEY = "current_turn_user_message_id"
CURRENT_TURN_STARTED_AT_KEY = "current_turn_started_at"
PAUSED_TURNS_METADATA_KEY = "approval_paused_turns"

NOT_RESUMABLE_NO_PAUSED_TURN = "no_paused_turn"
NOT_RESUMABLE_USER_MESSAGE_MISSING = "user_message_missing"


@dataclass(frozen=True, slots=True)
class PausedTurn:
    """A turn bound to an approval, ready to resume as its owner."""

    approval_id: str
    user_message_id: str
    owner_user_id: str
    prompt: str


@dataclass(frozen=True, slots=True)
class TurnNotResumable:
    """Explicit reason why an approval decision has no turn to resume."""

    approval_id: str
    reason: str


def begin_chat_turn(metadata: dict[str, Any], *, user_message_id: str, started_at: datetime) -> None:
    """Mark ``user_message_id`` as the turn in flight (both entry paths and resume)."""
    metadata[CURRENT_TURN_USER_MESSAGE_KEY] = user_message_id
    metadata[CURRENT_TURN_STARTED_AT_KEY] = started_at.isoformat()


def end_chat_turn(metadata: dict[str, Any]) -> None:
    """Clear the turn-in-flight marker; paused-turn bindings are kept."""
    metadata.pop(CURRENT_TURN_USER_MESSAGE_KEY, None)
    metadata.pop(CURRENT_TURN_STARTED_AT_KEY, None)


def hold_turn_for_approval(session: AgentSession, *, approval_id: str, requested_by: str) -> bool:
    """Bind ``approval_id`` to the turn in flight; ``False`` when no turn is in flight.

    Approvals raised outside a chat turn (task runs, tools called without a turn
    marker) have nothing to resume, so nothing is held for them.
    """
    metadata = dict(session.metadata_ or {})
    user_message_id = str(metadata.get(CURRENT_TURN_USER_MESSAGE_KEY) or "").strip()
    if not approval_id or not user_message_id:
        return False
    paused = dict(metadata.get(PAUSED_TURNS_METADATA_KEY) or {})
    paused[approval_id] = {
        "user_message_id": user_message_id,
        "owner_user_id": requested_by,
        "held_at": utc_now_aware().isoformat(),
    }
    metadata[PAUSED_TURNS_METADATA_KEY] = paused
    session.metadata_ = metadata
    return True


async def take_paused_turn(
    db: AsyncSession,
    session: AgentSession,
    *,
    approval_id: str,
) -> PausedTurn | TurnNotResumable:
    """Consume the turn bound to ``approval_id`` (one-shot)."""
    metadata = dict(session.metadata_ or {})
    paused = dict(metadata.get(PAUSED_TURNS_METADATA_KEY) or {})
    entry = paused.pop(approval_id, None)
    if not isinstance(entry, dict):
        return TurnNotResumable(approval_id=approval_id, reason=NOT_RESUMABLE_NO_PAUSED_TURN)
    metadata[PAUSED_TURNS_METADATA_KEY] = paused
    session.metadata_ = metadata

    user_message_id = str(entry.get("user_message_id") or "").strip()
    user_message = (
        await db.execute(
            select(Message).where(
                Message.id == user_message_id,
                Message.session_id == session.id,
                Message.role == "user",
            )
        )
    ).scalar_one_or_none()
    prompt = str(user_message.content or "").strip() if user_message is not None else ""
    if not prompt:
        return TurnNotResumable(approval_id=approval_id, reason=NOT_RESUMABLE_USER_MESSAGE_MISSING)
    return PausedTurn(
        approval_id=approval_id,
        user_message_id=user_message_id,
        owner_user_id=str(entry.get("owner_user_id") or ""),
        prompt=prompt,
    )


async def require_approval_decision_access(db: AsyncSession, *, approval: Approval, user_id: str) -> None:
    """Only a user with write access to the approval's session may decide it (404/403)."""
    await require_session_access(db, session_id=str(approval.session_id or ""), user_id=user_id, require_write=True)


__all__ = [
    "CURRENT_TURN_USER_MESSAGE_KEY",
    "NOT_RESUMABLE_NO_PAUSED_TURN",
    "NOT_RESUMABLE_USER_MESSAGE_MISSING",
    "PAUSED_TURNS_METADATA_KEY",
    "PausedTurn",
    "TurnNotResumable",
    "begin_chat_turn",
    "end_chat_turn",
    "hold_turn_for_approval",
    "require_approval_decision_access",
    "take_paused_turn",
]
