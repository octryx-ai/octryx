"""The newest turn's summary and ``Message`` rows of one inbound model call (``transcript``)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Message, TurnTrace
from ...redaction_policy import redact_secret_text
from .anthropic_stream import Observation
from .transcript_tools import result_excerpt
from .turn_delta import TurnDelta

MAX_PROMPT_CHARS = 20_000
MAX_ASSISTANT_CHARS = 20_000
MAX_DELTA_BLOCKS = 64


def _delta_summary(delta: TurnDelta) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": redact_secret_text(text, max_chars=MAX_PROMPT_CHARS)} for text in delta.user_texts
    ]
    blocks.extend(
        {
            "type": "tool_result",
            "tool_use_id": result.tool_use_id[:64],
            "is_error": result.is_error,
            "excerpt": result_excerpt(result.text),
        }
        for result in delta.tool_results
    )
    return [{"role": "user", "content": blocks[:MAX_DELTA_BLOCKS]}] if blocks else []


async def record_turn_messages(
    db: AsyncSession,
    *,
    session_id: str,
    body: Mapping[str, Any],
    observation: Observation,
    delta: TurnDelta,
    model: str,
    cost: Decimal,
) -> str | None:
    tools = body.get("tools")
    if not isinstance(tools, list) or not tools:
        return None
    prompt = delta.prompt_text()
    if prompt:
        messages = body.get("messages")
        position = len(messages) if isinstance(messages, list) else 0
        key = f"gw:u:{position}:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:40]}"
        seen = (
            await db.execute(
                select(Message.id).where(Message.session_id == session_id, Message.idempotency_key == key)
            )
        ).first()
        if seen is None:
            db.add(
                Message(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    role="user",
                    content=redact_secret_text(prompt, max_chars=MAX_PROMPT_CHARS),
                    idempotency_key=key,
                )
            )
    if observation.stop_reason == "end_turn" and observation.text.strip():
        answer_id = str(uuid.uuid4())
        db.add(
            Message(
                id=answer_id,
                session_id=session_id,
                role="assistant",
                content=redact_secret_text(observation.text, max_chars=MAX_ASSISTANT_CHARS),
                model=model,
                tokens_in=int(observation.usage.get("input_tokens") or 0),
                tokens_out=int(observation.usage.get("output_tokens") or 0),
                cost=cost,
                idempotency_key=f"gw:a:{uuid.uuid4().hex}",
            )
        )
        return answer_id
    return None


async def link_answer_trace(db: AsyncSession, trace: TurnTrace, answer_id: str | None) -> None:
    # The answer row is flushed first, so the trace's foreign key never points at an unwritten row.
    if answer_id:
        await db.flush()
        trace.message_id = answer_id


__all__ = [
    "delta_summary",
    "link_answer_trace",
    "record_turn_messages",
]


# Shared with the seat route (``seat_transcript.py``).
delta_summary = _delta_summary
