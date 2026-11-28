"""A run's chat sessions beyond the binding itself: a new bound thread, the thread's name, the hand-over rule and
the session's latest run."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, User, WorkflowRun, WorkflowRunSession
from ...models.runtime.secure_work import WorkItem
from .records import WorkflowRunError, active_run_for_session, bind_session, new_chat_session
from .states import ACTIVE_STATUSES


async def new_bound_session(db: AsyncSession, run: WorkflowRun, user: User) -> Session:
    session = await new_chat_session(db, user, run.project_id)
    await bind_session(db, run, session, actor_id=user.id)
    return session


async def _name_thread(db: AsyncSession, run: WorkflowRun, metadata: dict[str, Any]) -> None:
    from ..session.session_title import apply_run_title

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    title = f"{item.source_key} {item.title}" if item is not None and item.source_key else (
        item.title if item is not None else run.title)
    apply_run_title(metadata, title)


async def _refuse_foreign_binding(db: AsyncSession, run: WorkflowRun, session: Session) -> None:
    other = await active_run_for_session(db, session.id)
    if other is None or other.id == run.id or run.parent_run_id == other.id or other.parent_run_id == run.id:
        return
    raise WorkflowRunError("session_bound", f"This chat already follows the active run '{other.title}'; "
                                            "continue it there, or open a new chat.", 409)


async def _active_descendant(db: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    seen = {run.id}
    while run.status == "waiting" and run.waiting_kind == "sub_workflow":
        child = await db.get(WorkflowRun, str(dict(run.node_state or {}).get("child_run_id") or ""))
        if child is None or child.id in seen or child.status not in ACTIVE_STATUSES:
            break
        seen.add(child.id)
        run = child
    return run


async def run_for_session(db: AsyncSession, session_id: str) -> WorkflowRun | None:
    return (await db.execute(
        select(WorkflowRun)
        .join(WorkflowRunSession, WorkflowRunSession.run_id == WorkflowRun.id)
        .where(WorkflowRunSession.session_id == session_id, WorkflowRunSession.active.is_(True))
        .order_by(WorkflowRunSession.linked_at.desc())
        .limit(1)
    )).scalar_one_or_none()
