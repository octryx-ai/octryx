"""A run's device turns, read from its own events when its Tokens view is opened (a UI read, not a metric).

Per job and turn: the launcher's ``token_profile`` parts (measured), else the turn's usage, tool uses and results and
the job's first context reading (estimated); the phase is the node the platform started the job's turn for
(``device_continuation_started``), else the phase entered last before the turn.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DeviceJob, DeviceJobEvent, WorkflowRunEvent, WorkflowRunSession
from .assemble import KINDS, TurnFacts, positive, usage_call
from .split import Turn


async def _job_events(db: AsyncSession, run_id: str) -> list[DeviceJobEvent]:
    sessions = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == run_id)
    jobs = select(DeviceJob.id).where(DeviceJob.session_id.in_(sessions))
    rows = await db.execute(select(DeviceJobEvent).where(DeviceJobEvent.job_id.in_(jobs))
                            .order_by(DeviceJobEvent.job_id, DeviceJobEvent.seq))
    return list(rows.scalars())


async def _phase_marks(db: AsyncSession, run_id: str) -> tuple[dict[str, list[tuple[datetime, str]]],
                                                                  list[tuple[datetime, str]]]:
    rows = (await db.execute(select(WorkflowRunEvent.kind, WorkflowRunEvent.node_id, WorkflowRunEvent.detail,
                                    WorkflowRunEvent.created_at)
                             .where(WorkflowRunEvent.run_id == run_id,
                                    WorkflowRunEvent.kind.in_(("device_continuation_started", "node_entered")))
                             .order_by(WorkflowRunEvent.created_at))).all()
    by_job: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    entered: list[tuple[datetime, str]] = []
    for kind, node_id, detail, created_at in rows:
        detail = detail if isinstance(detail, dict) else {}
        if kind == "device_continuation_started" and detail.get("job_id") and node_id:
            by_job[str(detail["job_id"])].append((created_at, node_id))
        elif kind == "node_entered" and detail.get("kind") == "phase" and node_id:
            entered.append((created_at, node_id))
    return by_job, entered


def _latest(marks: list[tuple[datetime, str]], when: datetime) -> str:
    index = bisect_right([at for at, _node in marks], when)
    return marks[index - 1][1] if index else ""


async def run_turns(db: AsyncSession, run_id: str) -> list[Turn]:
    """The run's device turns in the order they ran, each with its phase."""
    by_job, entered = await _phase_marks(db, run_id)
    facts: dict[tuple[str, str], TurnFacts] = {}
    first_context: dict[str, int] = {}
    for event in await _job_events(db, run_id):
        body = event.body if isinstance(event.body, dict) else {}
        turn_id = str(body.get("turn_id") or "")
        if not turn_id:
            continue
        # Every event of a turn opens it (the first one dates it): a turn may report no tool events at all
        # (only its usage) and still counts.
        item = facts.setdefault((event.job_id, turn_id), TurnFacts(event.job_id, turn_id, event.created_at))
        if event.type == "turn_finished":
            item.turn.usage = usage_call(body.get("usage"))
            item.finished = True
        elif event.type == "job_event" and body.get("kind") in KINDS:
            if body.get("kind") == "context" and event.job_id not in first_context:
                first_context[event.job_id] = positive(body.get("tokens"))
            item.add(body)
    turns = []
    for item in sorted(facts.values(), key=lambda value: value.started):
        turn = item.build()
        if not turn.measured and not item.finished:
            continue  # a turn still running (or lost) has no usage yet
        turn.first_context = first_context.get(turn.job_id, 0)
        turn.node_id = _latest(by_job.get(turn.job_id, []), item.started) or _latest(entered, item.started)
        turns.append(turn)
    return turns


__all__ = ["run_turns"]
