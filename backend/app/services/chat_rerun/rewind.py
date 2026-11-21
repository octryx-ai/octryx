"""Rewinding a chat thread to a user message: what is dropped, what is superseded, what is reset."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    ChangePreview,
    ContextCheckpoint,
    Message,
    MessageFeedback,
    PrefetchCacheEntry,
    Session,
    SessionEntity,
    SessionToolCacheEntry,
    ThreadContext,
    ToolCall,
    ToolResultCompressionLog,
)
from ...time_utils import utc_now
from ..artifact_store import delete_tool_artifacts_for_tool_call_ids
from .run_history import supersede_rerun_history
from .targets import resolve_chat_rerun_target_message


@dataclass(frozen=True)
class ChatRewind:
    target_message: Message
    ordered_messages: list[Message]
    prompt: str


async def _ordered_messages(db: AsyncSession, session: Session) -> list[Message]:
    return (
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


async def _drop_later_history(
    db: AsyncSession, *, session: Session, cutoff: datetime, later_message_ids: list[str]
) -> None:
    """Delete what the replaced run produced; append-only history is superseded instead."""
    tool_call_filters = [ToolCall.session_id == session.id, ToolCall.created_at > cutoff]
    if later_message_ids:
        tool_call_filters[-1] = or_(ToolCall.created_at > cutoff, ToolCall.message_id.in_(later_message_ids))
    tool_call_ids = (await db.execute(select(ToolCall.id).where(*tool_call_filters))).scalars().all()

    if tool_call_ids:
        await delete_tool_artifacts_for_tool_call_ids(db, list(tool_call_ids))

    if later_message_ids:
        await db.execute(delete(MessageFeedback).where(MessageFeedback.message_id.in_(later_message_ids)))

    # Approval, trace and usage history is append-only: mark it superseded, never delete it.
    await supersede_rerun_history(
        db,
        session_id=session.id,
        cutoff=cutoff,
        later_message_ids=later_message_ids,
        superseded_at=utc_now(),
    )
    await db.execute(
        delete(ChangePreview).where(
            ChangePreview.session_id == session.id,
            ChangePreview.created_at > cutoff,
            ChangePreview.approval_id.is_(None),
        )
    )

    if tool_call_ids:
        await db.execute(delete(ToolCall).where(ToolCall.id.in_(tool_call_ids)))
    await db.execute(delete(ThreadContext).where(ThreadContext.session_id == session.id))
    await db.execute(delete(SessionToolCacheEntry).where(SessionToolCacheEntry.session_id == session.id))
    await db.execute(delete(PrefetchCacheEntry).where(PrefetchCacheEntry.session_id == session.id))
    await db.execute(delete(ContextCheckpoint).where(ContextCheckpoint.session_id == session.id))
    await db.execute(delete(SessionEntity).where(SessionEntity.session_id == session.id))
    await db.execute(delete(ToolResultCompressionLog).where(ToolResultCompressionLog.session_id == session.id))

    if later_message_ids:
        await db.execute(delete(Message).where(Message.id.in_(later_message_ids)))


def _reset_target(
    session: Session, target_message: Message, ordered_messages: list[Message], clean_prompt: str
) -> None:
    target_message.content = clean_prompt
    target_message.tool_calls = None
    target_message.tool_results = None
    target_message.model = None
    target_message.tokens_in = 0
    target_message.tokens_out = 0
    target_message.cost = 0

    metadata = dict(session.metadata_ or {})
    metadata.pop("last_stop_reason", None)
    metadata.pop("approval_grants", None)
    first_user_message = next((row for row in ordered_messages if row.role == "user"), None)
    if first_user_message and first_user_message.id == target_message.id:
        metadata["title"] = clean_prompt[:80]
    session.metadata_ = metadata


async def rewind_chat_history(
    db: AsyncSession,
    *,
    session: Session,
    target_message: Message,
    prompt: str,
) -> ChatRewind:
    """Drop the thread after the target user message and put ``prompt`` in it; nothing is committed.

    Shared by the server rerun (:func:`prepare_chat_rerun`) and the device rerun
    (``devices/chat_turn.start_device_turn``), which marks its own turn.
    """
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("Prompt is required")
    target_message = await resolve_chat_rerun_target_message(
        db,
        session=session,
        message=target_message,
    )

    ordered_messages = await _ordered_messages(db, session)
    target_index = next((index for index, row in enumerate(ordered_messages) if row.id == target_message.id), -1)
    if target_index < 0:
        raise ValueError("Target message is not part of the selected session")

    later_messages = ordered_messages[target_index + 1 :]
    later_message_ids = [row.id for row in later_messages]
    cutoff = target_message.created_at

    await _drop_later_history(db, session=session, cutoff=cutoff, later_message_ids=later_message_ids)
    _reset_target(session, target_message, ordered_messages, clean_prompt)
    return ChatRewind(target_message=target_message, ordered_messages=list(ordered_messages), prompt=clean_prompt)
