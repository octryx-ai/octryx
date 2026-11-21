from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, Session
from ...time_utils import utc_now
from ..session.run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state
from ..session.turn_approval_state import begin_chat_turn
from .rewind import rewind_chat_history


@dataclass(frozen=True)
class ChatRerunPreparation:
    session: Session
    target_message: Message
    prompt: str


def _chat_rerun_routing_resolution() -> dict:
    """The plain-chat routing resolution of a rerun on a thread that never recorded one.

    A rerun is a chat entry point like a send: without a recorded resolution the run would have no
    profile origin (``run_capability.resolution``, ``missing_declaration``) and the execution gate
    would refuse an ordinary chat message. The rerun runs as a chat turn without a workflow.
    """
    from ..workflow_routing.explicit_selection import explicit_mode_no_selection_resolution

    resolution = explicit_mode_no_selection_resolution()
    resolution["unmatched_reason"] = "chat rerun: no routing resolution was recorded on this thread."
    return resolution


async def prepare_chat_rerun(
    db: AsyncSession,
    *,
    session: Session,
    target_message: Message,
    prompt: str,
) -> ChatRerunPreparation:
    """Rewind the thread to ``target_message`` and mark it as the server turn in flight (commits)."""
    from ..workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

    rewound = await rewind_chat_history(db, session=session, target_message=target_message, prompt=prompt)
    target_message, clean_prompt = rewound.target_message, rewound.prompt
    turn_started_at = utc_now()
    metadata = dict(session.metadata_ or {})
    begin_chat_turn(metadata, user_message_id=target_message.id, started_at=turn_started_at)
    metadata.setdefault("run_started_at", turn_started_at.isoformat())
    if not isinstance(metadata.get(ROUTING_RESOLUTION_KEY), dict):
        metadata[ROUTING_RESOLUTION_KEY] = _chat_rerun_routing_resolution()
    session.metadata_ = metadata
    session.status = "running"
    session.ended_at = None
    set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    await db.commit()

    return ChatRerunPreparation(
        session=session,
        target_message=target_message,
        prompt=clean_prompt,
    )


__all__ = [
    "ChatRerunPreparation",
    "prepare_chat_rerun",
]
