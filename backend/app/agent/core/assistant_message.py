"""Persist an assistant message of a turn, with its trace and the structured thread context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message
from .runtime.trace_runtime import persist_turn_trace
from .runtime.turn_execution_binding import mark_turn_runtime_stopped
from .turn.thread_context import upsert_thread_context


def _latest_user_message(input_messages: list[dict[str, Any]]) -> str:
    for item in reversed(input_messages):
        if item.get("role") == "user":
            return str(item.get("content") or "")
    return ""


async def persist_assistant_message(
    *,
    db: AsyncSession,
    session_id: str,
    content: str,
    model: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> Message:
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=content,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    db.add(message)
    await db.commit()
    return message


async def persist_traced_assistant_message(
    *,
    db: AsyncSession,
    session_id: str,
    content: str,
    provider: str,
    model: str,
    input_messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    tool_trace: list[dict[str, Any]] | None = None,
    raw_output: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    trace_limits: dict[str, Any] | None = None,
    update_thread_context: bool = True,
    runtime_stop_reason: str | None = None,
) -> Message:
    """Persist an assistant message with its turn trace.

    ``update_thread_context=False`` is for platform-authored outcomes that did not run a
    model turn (for example a runtime-readiness block): the structured thread context keeps
    describing the last real turn instead of the platform notice. ``runtime_stop_reason``
    marks this trace as the turn's explicit runtime stop (closed reason).
    """
    message = await persist_assistant_message(
        db=db, session_id=session_id, content=content, model=model, tokens_in=tokens_in, tokens_out=tokens_out
    )
    trace = await persist_turn_trace(
        db=db,
        session_id=session_id,
        message_id=message.id,
        provider=provider,
        model=model,
        input_messages=input_messages,
        context_snapshot=context_snapshot,
        tool_trace=tool_trace or [],
        raw_output=raw_output or {"content": content},
        usage=usage or {},
        trace_limits=trace_limits,
    )
    if runtime_stop_reason:
        mark_turn_runtime_stopped(trace, runtime_stop_reason)
    if not update_thread_context:
        await db.commit()
        return message
    await upsert_thread_context(
        db=db,
        session_id=session_id,
        derived_from_message_id=message.id,
        current_user_message=_latest_user_message(input_messages),
        assistant_content=content,
        context_snapshot=context_snapshot,
        tool_trace=tool_trace or [],
        raw_output=raw_output or {"content": content},
    )
    await db.commit()
    return message
