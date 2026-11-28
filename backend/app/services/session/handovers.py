"""Handing a session to a named person or into its Workspace's pool; a workflow run moves with its thread."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Session, SessionCollaborator, SessionHandover, User, WorkflowRun
from ...time_utils import utc_now
from ..team_notification import create_notification
from .handover_pool import STATUS_PENDING, entry_needs, is_member

STATUS_ACCEPTED, STATUS_DECLINED, STATUS_WITHDRAWN = "accepted", "declined", "withdrawn"
SOURCE_HOLDER, SOURCE_ADMIN, SOURCE_SEAT = "holder", "admin", "seat_required"


class HandoverError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code, self.status_code = code, status_code


def serialize_handover(row: SessionHandover) -> dict[str, Any]:
    return {"id": row.id, "session_id": row.session_id, "run_id": row.run_id, "from_user_id": row.from_user_id,
            "to_user_id": row.to_user_id, "pool": row.to_user_id is None and row.status == STATUS_PENDING,
            "source": row.source, "needs": dict(row.needs or {}), "reason": row.reason,
            "context_summary": row.context_summary, "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None}


def _audit(db: AsyncSession, row: SessionHandover, action: str, actor_id: str, project_id: str | None) -> None:
    db.add(AuditLog(user_id=actor_id, action=f"session.handover.{action}", resource_type="session",
                    resource_id=row.session_id, project_id=project_id,
                    details={"handover_id": row.id, "run_id": row.run_id, "from": row.from_user_id,
                             "to": row.to_user_id}))


async def _withdraw_open(db: AsyncSession, session_id: str) -> None:
    await db.execute(update(SessionHandover).where(SessionHandover.session_id == session_id,
                                                   SessionHandover.status == STATUS_PENDING)
                     .values(status=STATUS_WITHDRAWN, resolved_at=utc_now()))


async def _source(db: AsyncSession, session: Session, run: WorkflowRun | None, user: User, to_pool: bool) -> str:
    from ..agent_board.messages import is_workspace_admin
    from ..workflow_runs.records import WorkflowRunError
    from ..workflow_runs.run_move import check_handover_request

    holder = (run.requested_by if run is not None else session.user_id) == user.id
    if holder:
        return SOURCE_HOLDER
    if to_pool and session.project_id and await is_workspace_admin(db, user.id, session.project_id):
        return SOURCE_ADMIN  # an absent person's session goes into the pool
    if run is not None:
        try:
            await check_handover_request(db, run, user=user, receiver=None)
        except WorkflowRunError as error:
            raise HandoverError(error.code, str(error), error.status_code) from error
        return SOURCE_ADMIN
    raise HandoverError("not_holder", "Only the session's holder hands it over.", 403)


async def hand_over(db: AsyncSession, *, user: User, session_id: str | None = None, run_id: str | None = None,
                    to_user_id: str | None = None, reason: str | None = None,
                    context_summary: str | None = None) -> SessionHandover:
    from ..workflow_runs.records import main_session_id

    run = await db.get(WorkflowRun, run_id) if run_id else None
    if run_id and run is None:
        raise HandoverError("unknown_run", "Unknown run.", 404)
    session = await db.get(Session, (await main_session_id(db, run)) if run is not None else (session_id or ""))
    if session is None:
        raise HandoverError("unknown_session", "Unknown session.", 404)
    source = await _source(db, session, run, user, to_pool=not to_user_id)
    receiver = await db.get(User, to_user_id) if to_user_id else None
    if to_user_id and (receiver is None or not receiver.is_active or receiver.id == session.user_id
                       or (session.project_id and not await is_member(db, receiver.id, session.project_id))):
        raise HandoverError("handover_receiver_invalid", "Choose another active member of the Workspace.", 422)
    await _withdraw_open(db, session.id)
    row = SessionHandover(session_id=session.id, run_id=run.id if run is not None else None,
                          from_user_id=session.user_id, to_user_id=to_user_id, source=source,
                          needs=await entry_needs(db, session, run), reason=(reason or "").strip()[:500] or None,
                          context_summary=(context_summary or "").strip() or None, status=STATUS_PENDING)
    db.add(row)
    await db.flush()
    await _announce(db, row, session, run, actor_id=user.id)
    return row


async def _announce(db: AsyncSession, row: SessionHandover, session: Session, run: WorkflowRun | None, *,
                    actor_id: str) -> None:
    from ..attention.stream import nudge_after_commit
    from ..workflow_runs.run_move import note_handover

    if run is not None:
        note_handover(db, run, "requested", actor_id=actor_id,
                      detail={"to": row.to_user_id, "pool": row.to_user_id is None, "reason": row.reason})
    _audit(db, row, "requested", actor_id, session.project_id)
    if row.to_user_id:
        await create_notification(db, user_id=row.to_user_id, notification_type="session.handover_requested",
                                  title="Session handover requested",
                                  body=row.reason or "A session was handed over to you.",
                                  link=f"/chat?session_id={session.id}", project_id=session.project_id,
                                  payload={"session_id": session.id, "handover_id": row.id})
        nudge_after_commit(db, row.to_user_id, event="handover_requested")


async def open_seat_entry(db: AsyncSession, run: WorkflowRun, needs: dict[str, str]) -> None:
    from ..workflow_runs.records import main_session_id

    session_id = await main_session_id(db, run)
    if not session_id or (await db.execute(select(SessionHandover.id).where(
            SessionHandover.run_id == run.id, SessionHandover.status == STATUS_PENDING))).first() is not None:
        return
    db.add(SessionHandover(session_id=session_id, run_id=run.id, from_user_id=str(run.requested_by),
                           source=SOURCE_SEAT, needs=needs, status=STATUS_PENDING,
                           reason="The run needs a seat that only a person's device holds."))


async def close_run_entries(db: AsyncSession, run: WorkflowRun, *, user_id: str) -> None:
    await db.execute(update(SessionHandover).where(SessionHandover.run_id == run.id,
                                                   SessionHandover.status == STATUS_PENDING)
                     .values(status=STATUS_ACCEPTED, to_user_id=user_id, resolved_at=utc_now()))


async def _pending(db: AsyncSession, handover_id: str, user: User) -> tuple[SessionHandover, Session]:
    row = await db.get(SessionHandover, handover_id)
    session = await db.get(Session, row.session_id) if row is not None else None
    if row is None or session is None or user.id not in (row.to_user_id, row.from_user_id) and not await is_member(
            db, user.id, session.project_id):
        raise HandoverError("unknown_handover", "Unknown handover.", 404)
    if row.status != STATUS_PENDING:
        raise HandoverError("handover_resolved", "This handover is already resolved.", 409)
    if row.to_user_id not in (None, user.id):
        raise HandoverError("not_receiver", "This session is handed over to someone else.", 403)
    return row, session


async def _claim(db: AsyncSession, row: SessionHandover, user: User) -> None:
    claimed = await db.execute(update(SessionHandover).where(
        SessionHandover.id == row.id, SessionHandover.status == STATUS_PENDING,
        or_(SessionHandover.to_user_id.is_(None), SessionHandover.to_user_id == user.id),
    ).values(status=STATUS_ACCEPTED, to_user_id=user.id, resolved_at=utc_now()).execution_options(
        synchronize_session=False))
    if claimed.rowcount != 1:
        raise HandoverError("handover_taken", "Someone else took this session first.", 409)
    await db.refresh(row)


async def _idle_job(db: AsyncSession, session_id: str) -> Any:
    from ..devices.job_state import BUSY_STATUSES
    from ..devices.jobs import thread_job

    job = await thread_job(db, session_id)
    if job is not None and job.status in BUSY_STATUSES:
        raise HandoverError("runtime_busy", "A turn of this session is still running: its holder stops it or it ends "
                                            "first.", 409)
    return job


async def _move_session(db: AsyncSession, session: Session, user: User, job: Any) -> str:
    from ..devices.job_state import STATUS_CLOSED, STATUS_IDLE

    previous = session.user_id
    if previous == user.id:
        return previous
    if job is not None and job.status == STATUS_IDLE:
        # The holder's open job never serves the taker: their next turn starts a job of their own.
        job.status, job.status_reason = STATUS_CLOSED, "handed_over"
    session.user_id = user.id
    kept = await db.get(SessionCollaborator, {"session_id": session.id, "user_id": previous})
    if kept is None:
        db.add(SessionCollaborator(session_id=session.id, user_id=previous, role="contributor", invited_by=user.id))
    else:
        kept.role, kept.invited_by, kept.joined_at = "contributor", user.id, utc_now()
    own = await db.get(SessionCollaborator, {"session_id": session.id, "user_id": user.id})
    if own is not None:
        await db.delete(own)
    return previous


async def take(db: AsyncSession, handover_id: str, *, user: User, runtime_target: Any = None) -> dict[str, Any]:
    from ..workflow_runs.records import WorkflowRunError
    from ..workflow_runs.run_move import move_run

    row, session = await _pending(db, handover_id, user)
    job = await _idle_job(db, session.id)
    await _claim(db, row, user)
    run = await db.get(WorkflowRun, row.run_id) if row.run_id else None
    previous = await _move_session(db, session, user, job)
    if run is not None:
        try:
            await move_run(db, run, row, user=user, runtime_target=runtime_target)
        except WorkflowRunError as error:
            raise HandoverError(error.code, str(error), error.status_code) from error
    _audit(db, row, "taken", user.id, session.project_id)
    if previous != user.id:
        await create_notification(db, user_id=previous, notification_type="session.handover_accepted",
                                  title="Session taken over", body=f"{user.display_name or user.username} took it.",
                                  link=f"/chat?session_id={session.id}", project_id=session.project_id,
                                  payload={"session_id": session.id, "handover_id": row.id})
    return {"handover": serialize_handover(row), "session_id": session.id}


async def decline(db: AsyncSession, handover_id: str, *, user: User, reason: str = "") -> SessionHandover:
    from ..workflow_runs.run_move import note_handover

    row, session = await _pending(db, handover_id, user)
    if row.to_user_id != user.id:
        raise HandoverError("pool_entry", "A pool entry is not declined: whoever can, takes it.", 409)
    row.status, row.resolved_at = STATUS_DECLINED, utc_now()
    run = await db.get(WorkflowRun, row.run_id) if row.run_id else None
    if run is not None:
        note_handover(db, run, "declined", actor_id=user.id, detail={"by": user.id, "reason": reason[:500]})
    _audit(db, row, "declined", user.id, session.project_id)
    await create_notification(db, user_id=row.from_user_id, notification_type="session.handover_declined",
                              title="Session handover declined", body=reason[:500] or None,
                              link=f"/chat?session_id={session.id}", project_id=session.project_id,
                              payload={"session_id": session.id, "handover_id": row.id})
    return row


async def my_handovers(db: AsyncSession, user: User, *, status: str | None = None) -> list[dict[str, Any]]:
    query = select(SessionHandover).where(or_(SessionHandover.from_user_id == user.id,
                                              SessionHandover.to_user_id == user.id))
    if status:
        query = query.where(SessionHandover.status == status)
    rows = (await db.execute(query.order_by(SessionHandover.created_at.desc()).limit(200))).scalars().all()
    return [serialize_handover(row) for row in rows]


__all__ = ["HandoverError", "close_run_entries", "decline", "hand_over", "my_handovers", "open_seat_entry",
           "serialize_handover", "take"]
