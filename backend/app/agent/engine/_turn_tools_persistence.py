"""Persistence helpers for synthesized tool assistant responses."""

from __future__ import annotations

import uuid
from typing import Any

from ...models import Message
from ...services.workflow_contracts.decisions import WORKFLOW_DECISION_REQUEST_KEY
from ..core.runtime.trace_runtime import persist_turn_trace
from ..core.turn.thread_context import upsert_thread_context


async def persist_synthesized_tool_assistant(
    *,
    db,
    session_id: str,
    runtime: dict[str, Any],
    response: dict[str, Any],
    request_messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    tool_results: list[dict[str, Any]],
    current_user_message: str,
    content: str,
    source: str,
    assistant_content: str,
    trace_limits: dict[str, Any] | None = None,
    workflow_decision_request: dict[str, Any] | None = None,
) -> Message:
    synthesized_msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=content,
        model=f"{runtime['provider_name']}/{response.get('model') or runtime['model']}",
        tokens_in=0,
        tokens_out=0,
    )
    db.add(synthesized_msg)
    await db.flush()
    raw_output = {
        "content": content,
        "source": source,
        "assistant_content": assistant_content,
        "tool_calls": response.get("tool_calls") or [],
    }
    if workflow_decision_request:
        # Structured options of a workflow clarification (engine/decisions.py); the
        # turn execution summary re-validates them for the chat UI.
        raw_output[WORKFLOW_DECISION_REQUEST_KEY] = workflow_decision_request
    await persist_turn_trace(
        db=db,
        session_id=session_id,
        message_id=synthesized_msg.id,
        provider=runtime["provider_name"],
        model=response.get("model") or runtime["model"],
        input_messages=request_messages,
        context_snapshot=context_snapshot,
        tool_trace=tool_results,
        raw_output=raw_output,
        usage=response.get("usage", {}),
        trace_limits=trace_limits,
    )
    await upsert_thread_context(
        db=db,
        session_id=session_id,
        derived_from_message_id=synthesized_msg.id,
        current_user_message=current_user_message,
        assistant_content=content,
        context_snapshot=context_snapshot,
        tool_trace=tool_results,
        raw_output=raw_output,
    )
    await db.commit()
    return synthesized_msg


__all__ = ["persist_synthesized_tool_assistant"]
