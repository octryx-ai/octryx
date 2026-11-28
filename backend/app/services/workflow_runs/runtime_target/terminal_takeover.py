"""A person's octryx-claude terminal that attaches to a run on the server runners takes it over: the run's target
becomes the terminal, recorded as a runtime change, and the pool's pending or running turn ends."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ...devices.run_trace import GATEWAY_JOB_KEY
from ..records import main_session_id, record_event
from .switch import EVENT_CHANGED
from .target import KIND_TERMINAL, apply_to_thread, stored_target, with_target


def is_terminal_session(gateway_session: Session) -> bool:
    # A device or runner job's own session works for the run's target; only a person's terminal takes over.
    return not str(dict(gateway_session.metadata_ or {}).get(GATEWAY_JOB_KEY) or "")


async def take_over_for_terminal(db: AsyncSession, run: WorkflowRun, gateway_session: Session, *,
                                 actor_id: str) -> bool:
    from ...devices.agent_runtime import stop_session_jobs
    from ..octryx.continuation_marker import CONTEXT_KEY as CONTINUATION_KEY

    previous = stored_target(run)
    if not previous or not previous.get("pool") or not is_terminal_session(gateway_session):
        return False
    target = {"kind": KIND_TERMINAL}
    context = with_target(run.context, target, actor_id=actor_id)
    context.pop(CONTINUATION_KEY, None)  # the pool's pending turn never starts: the terminal does the phase
    run.context = context
    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    apply_to_thread(thread, target)
    if thread is not None:
        await stop_session_jobs(db, session_id=thread.id, actor_id=thread.user_id)
    record_event(db, run, EVENT_CHANGED, node_id=run.current_node_id, actor_id=actor_id,
                 detail={"from": previous, "to": target, "cause": "terminal_attached"})
    return True


__all__ = ["is_terminal_session", "take_over_for_terminal"]
