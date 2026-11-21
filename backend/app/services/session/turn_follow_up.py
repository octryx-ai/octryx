"""The follow-up of a completed chat turn, after its end state is committed.

Scheduled by :func:`services.session.turn_settlement.settle_turn_after_stream` for
every entry path, only when the turn ended ``completed``. It runs as a chat-turn
background task on its own database sessions, so it never extends the turn:

1. the session workspace's completion sync;
2. the ``session.completed`` outbound webhook;
3. the Memory capture, then the Episode capture (bounded; off unless the Workspace
   enables them).

A failure of steps 1-2 is logged and rolled back; it never changes the turn's state.
"""

from __future__ import annotations

import logging
from typing import Any

from ...models import Session as AgentSession
from ..chat_turn_background import schedule_chat_turn_background_task
from ..knowledge.episodes.turn_capture import run_turn_episode_capture
from ..knowledge.memory.auto_capture import run_turn_memory_capture
from ..outbound_webhook import emit_outbound_webhook_event
from .run_state import RUN_STATUS_COMPLETED
from .turn_event_payloads import completed_webhook_payload
from .workspace import get_session_workspace_root
from .workspace_sync import sync_workspace_full

logger = logging.getLogger(__name__)


async def run_completion_follow_up(
    *,
    session_factory,
    session_id: str,
    request_id: str | None,
    completion_follow_up: dict[str, Any],
) -> None:
    async with session_factory() as follow_up_db:
        try:
            session = await follow_up_db.get(AgentSession, session_id)
            if session is not None:
                workspace_root = await get_session_workspace_root(follow_up_db, session_id, create=False)
                sync_result = await sync_workspace_full(
                    db=follow_up_db,
                    session_id=session_id,
                    workspace_root=workspace_root,
                    reason="session_completed",
                )
                if sync_result.get("status") == "error":
                    logger.warning(
                        "Session workspace completion sync failed",
                        extra={"session_id": session_id, "sync": sync_result},
                    )
            await emit_outbound_webhook_event(
                follow_up_db,
                event_type="session.completed",
                project_id=completion_follow_up["project_id"],
                request_id=request_id,
                payload=completed_webhook_payload(
                    session_id=completion_follow_up["session_id"],
                    agent_type=completion_follow_up["agent_type"],
                    run_status=RUN_STATUS_COMPLETED,
                    run_completion_reason=str(completion_follow_up["completion_reason"] or ""),
                    latest_assistant_message_id=completion_follow_up["latest_assistant_message_id"],
                    latest_assistant_content=completion_follow_up["latest_assistant_content"],
                ),
            )
            await follow_up_db.commit()
        except Exception:
            await follow_up_db.rollback()
            logger.exception(
                "Failed to finish post-completion follow-up",
                extra={"session_id": session_id},
            )
    # After the turn and its follow-up are persisted; bounded, off unless the Workspace enables them.
    await run_turn_memory_capture(session_factory=session_factory, session_id=session_id)
    await run_turn_episode_capture(session_factory=session_factory, session_id=session_id)


def schedule_completion_follow_up(
    *,
    session_factory,
    session_id: str,
    request_id: str | None,
    completion_follow_up: dict[str, Any],
) -> None:
    follow_up_payload = dict(completion_follow_up)
    schedule_chat_turn_background_task(
        session_id=session_id,
        task_name="completion_follow_up",
        coro_factory=lambda: run_completion_follow_up(
            session_factory=session_factory,
            session_id=session_id,
            request_id=request_id,
            completion_follow_up=follow_up_payload,
        ),
    )


__all__ = ["run_completion_follow_up", "schedule_completion_follow_up"]
