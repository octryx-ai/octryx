"""Shared turn-state persistence helpers for the agent engine."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Message, ThreadContext
from ....tools.argument_sanitizers import publishable_tool_call_payloads
from ..runtime.trace_runtime import persist_turn_trace
from ..types import AgentResponse, ChatMessage, ContextSnapshot, ToolCall
from .thread_context import upsert_thread_context


def _latest_user_message_content(messages: list[ChatMessage] | None) -> str:
    for message in reversed(messages or []):
        if isinstance(message, dict) and str(message.get("role") or "") == "user":
            return str(message.get("content") or "")
    return ""


async def persist_runtime_assistant_response(
    *,
    db: AsyncSession,
    session_id: str,
    provider: str,
    model: str,
    request_messages: list[ChatMessage],
    context_snapshot: ContextSnapshot,
    response: AgentResponse,
    runtime_attempts: list[dict[str, Any]],
    content: str | None,
    tool_calls: list[ToolCall] | None,
    trace_limits: dict[str, Any] | None = None,
) -> tuple[Message, Any]:
    # The assistant row and the turn trace are written before the call they
    # describe is governed, so they keep the publishable projection of each
    # request rather than the raw arguments the model emitted.
    tool_calls = publishable_tool_call_payloads(tool_calls)
    assistant_msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=content,
        tool_calls=tool_calls,
        model=response.get("model", model),
        tokens_in=response.get("usage", {}).get("prompt_tokens", 0),
        tokens_out=response.get("usage", {}).get("completion_tokens", 0),
    )
    db.add(assistant_msg)
    await db.flush()
    turn_trace = await persist_turn_trace(
        db=db,
        session_id=session_id,
        message_id=assistant_msg.id,
        provider=provider,
        model=response.get("model", model),
        input_messages=request_messages,
        context_snapshot=context_snapshot,
        tool_trace=[],
        raw_output={
            "content": content,
            "tool_calls": tool_calls or [],
            "runtime_attempts": runtime_attempts,
            "thinking": str(response.get("thinking") or ""),
        },
        usage=response.get("usage", {}),
        trace_limits=trace_limits,
    )
    return assistant_msg, turn_trace


async def persist_suppressed_runtime_response(
    *,
    db: AsyncSession,
    session_id: str,
    provider: str,
    model: str,
    request_messages: list[ChatMessage],
    context_snapshot: ContextSnapshot,
    response: AgentResponse,
    raw_output: dict[str, Any],
    trace_limits: dict[str, Any] | None = None,
) -> None:
    await persist_turn_trace(
        db=db,
        session_id=session_id,
        message_id=None,
        provider=provider,
        model=response.get("model", model),
        input_messages=request_messages,
        context_snapshot=context_snapshot,
        tool_trace=[],
        raw_output=raw_output,
        usage=response.get("usage", {}),
        trace_limits=trace_limits,
    )
    await upsert_thread_context(
        db=db,
        session_id=session_id,
        derived_from_message_id=None,
        current_user_message=_latest_user_message_content(request_messages),
        assistant_content=str(raw_output.get("content") or ""),
        context_snapshot=context_snapshot,
        tool_trace=[],
        raw_output=raw_output,
    )
    await db.commit()


async def persist_runtime_thread_context(
    *,
    db: AsyncSession,
    session_id: str,
    message_id: str,
    current_user_message: str,
    assistant_content: str,
    context_snapshot: ContextSnapshot,
    tool_trace: list[dict[str, Any]],
    raw_output: dict[str, Any],
) -> dict[str, Any]:
    updated_thread_context = await upsert_thread_context(
        db=db,
        session_id=session_id,
        derived_from_message_id=message_id,
        current_user_message=current_user_message,
        assistant_content=assistant_content,
        context_snapshot=context_snapshot,
        tool_trace=tool_trace,
        raw_output=raw_output,
    )
    return dict(updated_thread_context.context_json or {})


async def fetch_thread_context_state(db: AsyncSession, session_id: str) -> dict[str, Any]:
    row = (await db.execute(select(ThreadContext).where(ThreadContext.session_id == session_id))).scalar_one_or_none()
    return dict(row.context_json or {}) if row and isinstance(row.context_json, dict) else {}
