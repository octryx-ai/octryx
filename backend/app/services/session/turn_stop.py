"""Stop the running turn of a session: one cancel path for every entry path. The task is in ``CHAT_RUN_TASKS`` whether
it runs in the background or inside a request; cancelling lets the runner settle the turn."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from .remote_stop import record_remote_stop_request
from .stop import finalize_user_stopped_session
from .turn_tasks import CHAT_RUN_TASKS

logger = logging.getLogger(__name__)

CANCEL_WAIT_SECONDS = 2


async def cancel_running_turn(session_id: str) -> bool:
    task = CHAT_RUN_TASKS.get(session_id)
    if task is None or task.done():
        return False
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=CANCEL_WAIT_SECONDS)
    except asyncio.CancelledError:
        pass
    except TimeoutError:
        logger.warning("chat.turn.stop.cancel_timeout", extra={"session_id": session_id})
    return True


async def stop_session_turn(db: AsyncSession, session: AgentSession) -> None:
    # A turn another live process runs is cancelled there: the stop records a request its ``RemoteTurnStopWatcher`` acts
    # on within about a second.
    from ..devices.agent_runtime import stop_session_jobs

    cancelled_here = await cancel_running_turn(session.id)
    # The thread's turn on a device or server runner stops too (the person's own jobs only).
    await stop_session_jobs(db, session_id=session.id, actor_id=str(session.user_id or ""))
    await db.refresh(session)
    if not cancelled_here:
        record_remote_stop_request(db, session)
    await finalize_user_stopped_session(db, session=session)
    await db.commit()


__all__ = ["CANCEL_WAIT_SECONDS", "cancel_running_turn", "stop_session_turn"]
