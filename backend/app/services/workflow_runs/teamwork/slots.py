"""Which device jobs count against the device's parallel limit while a team works (a team must not be slowed down by its
own bookkeeping)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from . import WORK_KEY


def _at_parallel_node(context: Any, current_node_id: str | None) -> bool:
    work = dict(dict(context or {}).get(WORK_KEY) or {})
    return bool(work) and work.get("node_id") == current_node_id and not work.get("route")


async def slot_free_sessions(db: Any, session_ids: list[str]) -> set[str]:
    from ....models import WorkflowRun, WorkflowRunSession
    from ..records import ROLE_MAIN

    wanted = sorted({str(item) for item in session_ids if item})
    if not wanted:
        return set()
    rows = (await db.execute(
        select(WorkflowRunSession.session_id, WorkflowRun.context, WorkflowRun.current_node_id)
        .join(WorkflowRun, WorkflowRun.id == WorkflowRunSession.run_id)
        .where(WorkflowRunSession.session_id.in_(wanted), WorkflowRunSession.role == ROLE_MAIN,
               WorkflowRunSession.active.is_(True), WorkflowRun.status == "running"))).all()
    free = {str(session_id) for session_id, context, node_id in rows if _at_parallel_node(context, node_id)}
    return free | await _review_threads(db, wanted)


async def _review_threads(db: Any, session_ids: list[str]) -> set[str]:
    from ....models import Session
    from ..review.seat import is_review_thread

    rows = (await db.execute(select(Session).where(Session.id.in_(session_ids)))).scalars().all()
    return {str(row.id) for row in rows if is_review_thread(row)}


async def slot_free(db: Any, session_id: str | None) -> bool:
    return bool(session_id) and session_id in await slot_free_sessions(db, [str(session_id)])


__all__ = ["slot_free", "slot_free_sessions"]
