"""Create, bind, read and record workflow runs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm.attributes import set_committed_value

from ...models import (
    Session,
    User,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunSession,
)
from ...models.runtime.secure_work import WorkItem
from ...time_utils import utc_now
from .states import (
    ACTIVE_STATUSES,
    EVENT_SESSION_BOUND,
    ROLE_MAIN,
    RUNTIME_CHAT,
)

RUN_METADATA_KEY = "workflow_run_id"
MAX_CLAIM_ATTEMPTS = 5
_CLAIMS = "workflow_run_claims"


class WorkflowRunError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 409, *, persist: bool = False,
                 state: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.state = state
        # The refusal changed the run (a refreshed confirmation payload): the caller commits before answering.
        self.persist = persist


@event.listens_for(OrmSession, "after_commit")
@event.listens_for(OrmSession, "after_rollback")
def _forget_claims(session: OrmSession) -> None:
    session.info.pop(_CLAIMS, None)


async def lock_run(db: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    # Claim before any change: a re-read discards unflushed changes.
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    claims = db.info.setdefault(_CLAIMS, {})
    if claims.get(run.id) == run.state_version:
        return run
    for _ in range(MAX_CLAIM_ATTEMPTS):
        seen = int(run.state_version or 0)
        result = await db.execute(
            update(WorkflowRun).where(WorkflowRun.id == run.id, WorkflowRun.state_version == seen)
            .values(state_version=seen + 1).execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            set_committed_value(run, "state_version", seen + 1)
            claims[run.id] = seen + 1
            return run
        await db.refresh(run)
    raise WorkflowRunError("run_busy", "The run is changing right now; try again.", 409)


async def reclaim_run(db: AsyncSession, run: WorkflowRun) -> bool:
    # False means another writer changed the run: the caller no longer owns it and must stop, never re-read and go on.
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    claims = db.info.setdefault(_CLAIMS, {})
    if claims.get(run.id) == run.state_version:
        return True
    seen = int(run.state_version or 0)
    result = await db.execute(
        update(WorkflowRun).where(WorkflowRun.id == run.id, WorkflowRun.state_version == seen)
        .values(state_version=seen + 1).execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    set_committed_value(run, "state_version", seen + 1)
    claims[run.id] = seen + 1
    return True


async def lock_run_id(db: AsyncSession, run_id: str | None) -> WorkflowRun | None:
    run = await db.get(WorkflowRun, run_id) if run_id else None
    return await lock_run(db, run) if run is not None else None


def record_event(
    db: AsyncSession, run: WorkflowRun, kind: str, *, node_id: str | None = None,
    detail: dict[str, Any] | None = None, actor_id: str | None = None,
) -> WorkflowRunEvent:
    event = WorkflowRunEvent(run_id=run.id, kind=kind, node_id=node_id, detail=dict(detail or {}),
                             actor_id=actor_id)
    db.add(event)
    run.updated_at = utc_now()
    from ..attention.stream import NUDGE_EVENT_KINDS, job_changed_after_commit, nudge_after_commit

    if kind not in NUDGE_EVENT_KINDS:
        job_changed_after_commit(db, run.id)
        return event
    nudge_after_commit(db, run.requested_by, run_id=run.id, event=kind)
    if run.responsible_user_id and run.responsible_user_id != run.requested_by:
        nudge_after_commit(db, run.responsible_user_id, run_id=run.id, event=kind)
    return event


def ticket_key_of(item: WorkItem | None) -> str | None:
    if item is None or str(item.source_type or "").lower() != "jira":
        return None
    return item.source_key


async def start_run(
    db: AsyncSession,
    *,
    user: User,
    workflow_key: str,
    project_id: str | None = None,
    work_item_id: str | None = None,
    repository: str | None = None,
    branch: str | None = None,
    session: Session | None = None,
    parent: WorkflowRun | None = None,
    parent_node_id: str | None = None,
    ticket_key: str | None = None,
    context: dict[str, Any] | None = None,
    runtime_target: Any = None,
    automatic: bool = False,
    responsible: tuple[str | None, str | None] | None = None,
) -> WorkflowRun:
    # The runtime target is set before the first node runs, so every runtime step runs there.
    from .engine import start_phased_run
    from .run_start import plan_start

    plan = await plan_start(db, user=user, workflow_key=workflow_key, project_id=project_id, work_item_id=work_item_id,
                            repository=repository, session=session, parent=parent, context=context,
                            runtime_target=runtime_target, automatic=automatic, responsible=responsible)
    flow, version = plan.phased
    return await start_phased_run(db, user=user, flow=flow, version=version, project_id=plan.scope,
                                  item=plan.item, repository=plan.repository, branch=branch, session=session,
                                  parent=parent, parent_node_id=parent_node_id, ticket_key=ticket_key,
                                  context=plan.context, responsible=plan.responsible)


def has_done_criteria(contract: dict[str, Any]) -> bool:
    from ..workflow_checks.library import workflow_checks
    from ..workflow_checks.steps import step_checks

    return bool(workflow_checks(contract) or step_checks(contract))


async def new_chat_session(db: AsyncSession, user: User, project_id: str | None) -> Session:
    session = Session(user_id=user.id, project_id=project_id, status="active", origin="chat", metadata_={})
    db.add(session)
    await db.flush()
    return session


async def bind_session(
    db: AsyncSession, run: WorkflowRun, session: Session, *, actor_id: str | None = None,
    role: str = ROLE_MAIN, runtime: str = RUNTIME_CHAT,
) -> WorkflowRunSession:
    from .run_sessions import _active_descendant, _name_thread, _refuse_foreign_binding

    run = await _active_descendant(db, run)
    await _refuse_foreign_binding(db, run, session)
    await db.execute(
        update(WorkflowRunSession)
        .where(WorkflowRunSession.run_id == run.id, WorkflowRunSession.role == role,
               WorkflowRunSession.active.is_(True))
        .values(active=False)
        .execution_options(synchronize_session=False)
    )
    # A session follows one run at a time.
    await db.execute(
        update(WorkflowRunSession)
        .where(WorkflowRunSession.session_id == session.id, WorkflowRunSession.active.is_(True))
        .values(active=False)
        .execution_options(synchronize_session=False)
    )
    binding = WorkflowRunSession(run_id=run.id, session_id=session.id, role=role, runtime=runtime, active=True)
    db.add(binding)
    metadata = dict(session.metadata_ or {})
    metadata[RUN_METADATA_KEY] = run.id
    if role == ROLE_MAIN and runtime == RUNTIME_CHAT:
        await _name_thread(db, run, metadata)
    session.metadata_ = metadata
    if not session.project_id and run.project_id:
        session.project_id = run.project_id
    record_event(db, run, EVENT_SESSION_BOUND, actor_id=actor_id,
                 detail={"session_id": session.id, "role": role, "runtime": runtime})
    await db.flush()
    return binding


async def active_run_for_session(db: AsyncSession, session_id: str | None) -> WorkflowRun | None:
    if not session_id:
        return None
    row = (await db.execute(
        select(WorkflowRun)
        .join(WorkflowRunSession, WorkflowRunSession.run_id == WorkflowRun.id)
        .where(WorkflowRunSession.session_id == session_id, WorkflowRunSession.active.is_(True),
               WorkflowRun.status.in_(tuple(ACTIVE_STATUSES)))
        .order_by(WorkflowRunSession.linked_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return row


async def main_session_id(db: AsyncSession, run: WorkflowRun) -> str | None:
    return (await db.execute(
        select(WorkflowRunSession.session_id)
        .where(WorkflowRunSession.run_id == run.id, WorkflowRunSession.role == ROLE_MAIN,
               WorkflowRunSession.active.is_(True))
        .order_by(WorkflowRunSession.linked_at.desc())
        .limit(1)
    )).scalar_one_or_none()


__all__ = [
    "RUN_METADATA_KEY",
    "WorkflowRunError",
    "active_run_for_session",
    "bind_session",
    "has_done_criteria",
    "lock_run",
    "lock_run_id",
    "new_chat_session",
    "main_session_id",
    "record_event",
    "start_run",
]
