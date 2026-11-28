"""A workflow run whose server turn a restart interrupted pauses instead of staying ``running``."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, WorkflowRun, WorkflowRunSession
from .limits import pause_run
from .records import WorkflowRunError, lock_run
from .states import PAUSE_RUNTIME_FAILED, STATUS_RUNNING

INTERRUPTED_BY_RESTART = "interrupted_by_restart"
MESSAGE = (
    "The platform restarted while this phase's agent turn was running, so the turn ended unfinished "
    "(interrupted_by_restart). Continue to run the phase again, or abort the run."
)


def _runs_on_device(session: Session) -> bool:
    target = dict(session.metadata_ or {}).get("execution_target")
    return isinstance(target, dict) and target.get("kind") == "device"


async def pause_runs_of_interrupted_sessions(db: AsyncSession, sessions: Iterable[Session]) -> list[str]:
    threads = {session.id: session for session in sessions if not _runs_on_device(session)}
    if not threads:
        return []
    run_ids = (await db.execute(
        select(WorkflowRunSession.run_id).where(
            WorkflowRunSession.session_id.in_(tuple(threads)),
            WorkflowRunSession.role == "main",
            WorkflowRunSession.active.is_(True),
        )
    )).scalars().all()
    paused: list[str] = []
    for run_id in dict.fromkeys(run_ids):
        run = await db.get(WorkflowRun, run_id)
        if run is None or run.status != STATUS_RUNNING:
            continue
        try:
            run = await lock_run(db, run)
        except WorkflowRunError:
            continue  # someone moved the run in between: it is not orphaned
        if run.status != STATUS_RUNNING:
            continue
        await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
            "message": MESSAGE, "code": INTERRUPTED_BY_RESTART,
            "resume": {"kind": "restart", "node_id": run.current_node_id},
        })
        paused.append(run.id)
    return paused


__all__ = ["INTERRUPTED_BY_RESTART", "pause_runs_of_interrupted_sessions"]
