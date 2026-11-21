"""Model-visible session history without runtime-readiness-blocked turns.

A turn stopped by the runtime-readiness gate
(``agent/engine/pre_dispatch/_runtime_readiness_block.py``) persists the user's prompt
followed by the gate's ``needs_configuration`` explanation. That turn never reached a
model, and the explanation is platform-authored, not a model answer. Replayed as history it
steered the next turn live on Bedrock: a kept stale prompt was answered instead of the
latest one, and a kept explanation was repeated verbatim. A blocked turn is therefore
removed as a unit from the persisted history before anything derives model input from it:
history counts, context compaction, the recent window, the relevance filter, and the
rolling session summary. The persisted messages stay visible in the session, and the user
re-sends the blocked request as the explanation instructs.

Gate replies are identified by their persisted turn-trace provider, never by content. The
blocked prompt is the ``user`` row immediately before a gate reply, because the gate
persists its reply right after the turn's prompt. Two preconditions follow and are not
enforced here: the gate trace must outlive its message (``turn_traces`` retention not
shorter than ``messages`` retention), and no other row may land between a blocked prompt
and its reply (no concurrent turns on one session).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Message, TurnTrace
from ....services.session.runtime_readiness_gate import RUNTIME_READINESS_GATE_TRACE_PROVIDER


async def exclude_runtime_readiness_blocked_turns(
    db: AsyncSession,
    *,
    session_id: str,
    messages: Sequence[Message],
) -> list[Message]:
    """Return the session's ``messages`` (oldest first) without runtime-readiness-blocked turns."""
    if not any(message.role == "assistant" for message in messages):
        return list(messages)
    gate_reply_ids = set(
        (
            await db.execute(
                select(TurnTrace.message_id).where(
                    TurnTrace.session_id == session_id,
                    TurnTrace.provider == RUNTIME_READINESS_GATE_TRACE_PROVIDER,
                )
            )
        )
        .scalars()
        .all()
    )
    if not gate_reply_ids:
        return list(messages)
    excluded_ids: set[str] = set()
    for index, message in enumerate(messages):
        if message.id not in gate_reply_ids:
            continue
        excluded_ids.add(message.id)
        if index > 0 and messages[index - 1].role == "user":
            excluded_ids.add(messages[index - 1].id)
    return [message for message in messages if message.id not in excluded_ids]


__all__ = ["exclude_runtime_readiness_blocked_turns"]
