"""Stop the running turn of a session: one cancel path for every entry path.

The turn's task is registered in ``turn_tasks.CHAT_RUN_TASKS`` whether it runs in the
background (``/chat/api``, approval resume) or inside a ``/api/v1`` request
(``turn_runner.run_request_turn``). Cancelling it lets the runner settle the turn
(``turn_failure.settle_cancelled_turn``: "Generation stopped by user."); then the session
is finalized as user-stopped (``stop.finalize_user_stopped_session``) and committed.
Callers: ``/chat/api/sessions/{id}/stop``, ``/api/v1/sessions/{id}/stop`` and the
coordinator ``stop`` control. A turn owned by another process is stopped through
``remote_stop``.
"""

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
    """Cancel the session's registered turn task; ``True`` when one was running."""
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
    """Cancel the running turn and persist the user-stopped state of ``session``.

    A turn another live process runs (a sibling API process, the platform worker) is cancelled there:
    the stop records a request its ``RemoteTurnStopWatcher`` acts on within about a second.
    """
    cancelled_here = await cancel_running_turn(session.id)
    await db.refresh(session)
    if not cancelled_here:
        record_remote_stop_request(db, session)
    await finalize_user_stopped_session(db, session=session)
    await db.commit()


__all__ = ["CANCEL_WAIT_SECONDS", "cancel_running_turn", "stop_session_turn"]
