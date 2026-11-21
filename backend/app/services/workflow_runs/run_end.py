"""The end of a phased run: completed at an outcome (a child, triage or epic goes on) or failed."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from .records import record_event
from .states import EVENT_COMPLETED, EVENT_FAILED, STATUS_COMPLETED, STATUS_FAILED


async def _finish(db: AsyncSession, run: WorkflowRun, *, outcome: str, actor_id: str | None) -> None:
    run.status, run.outcome, run.completed_at, run.waiting_kind = STATUS_COMPLETED, outcome, utc_now(), None
    record_event(db, run, EVENT_COMPLETED, node_id=run.current_node_id, actor_id=actor_id, detail={"outcome": outcome})
    if run.parent_run_id:
        from .sub_workflows import child_finished

        await child_finished(db, run, actor_id=actor_id)
        return
    from .triage_routing import route_after_triage

    await route_after_triage(db, run, actor_id=actor_id)  # a triage starts its type's follow-up
    from .epic_chain import continue_epic

    await continue_epic(db, run, actor_id=actor_id)  # an epic works through its stories by itself


async def fail_run(db: AsyncSession, run: WorkflowRun, message: str) -> None:
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    run.status, run.last_error, run.completed_at, run.waiting_kind = STATUS_FAILED, message, utc_now(), None
    record_event(db, run, EVENT_FAILED, node_id=run.current_node_id, detail={"error": message})
    from .teamwork.item_stop import stop_jobs

    await stop_jobs(db, run, actor_id=None)  # a failed run's item turns never go on working
    if run.parent_run_id:
        from .sub_workflows import child_finished

        await child_finished(db, run, actor_id=None)
