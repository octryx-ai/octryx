"""The Workspace session pool: what an entry needs, who can run it now, and what a member sees of it."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, SessionHandover, User, UserProject, WorkflowRun
from ..devices.seat_engines import PROFILE_SEAT
from ..project.private_workspace import outside_foreign_private

STATUS_PENDING = "pending"
PROFILE_GOVERNED = "governed"


async def entry_needs(db: AsyncSession, session: Session, run: WorkflowRun | None) -> dict[str, str]:
    from ..agent_gateway.engine_policy import effective_engine
    from ..devices.chat_turn import EXECUTION_TARGET_METADATA_KEY
    from ..devices.engine_state import snapshot_of
    from ..workflow_runs.review.choice import run_engine
    from ..workflow_runs.runtime_target.target import stored_target

    if run is not None:
        target = stored_target(run) or {}
        return {"engine": await run_engine(db, run), "profile": str(target.get("profile") or PROFILE_GOVERNED)}
    target = dict(dict(session.metadata_ or {}).get(EXECUTION_TARGET_METADATA_KEY) or {})
    engine = str(snapshot_of(session).get("engine") or "") or (await effective_engine(
        db, user_id=session.user_id, workspace_id=session.project_id or "")).engine
    return {"engine": engine, "profile": str(target.get("profile") or PROFILE_GOVERNED)}


async def can_run_now(db: AsyncSession, user: User, needs: dict[str, Any] | None, workspace_id: str | None) -> bool:
    from ..devices.runner_pool import pool_allowed, runners_online
    from ..devices.seat_engines import online_devices, runs_engine, seat_devices

    needs = dict(needs or {})
    engine = str(needs.get("engine") or "")
    if needs.get("profile") == PROFILE_SEAT:  # a person's seat never reaches a server runner
        return bool(await seat_devices(db, user.id, engine))
    if any(PROFILE_GOVERNED in list(device.profiles or []) and runs_engine(device, engine)
           for device in await online_devices(db, user.id)):
        return True
    return bool(await runners_online(db)) and await pool_allowed(db, workspace_id)


async def is_member(db: AsyncSession, user_id: str, workspace_id: str | None) -> bool:
    if not workspace_id:
        return False
    return await db.get(UserProject, {"user_id": user_id, "project_id": workspace_id}) is not None


def _still_open(row: SessionHandover, run: WorkflowRun | None) -> bool:
    from ..workflow_runs.runtime_target.seat_required import seat_paused
    from ..workflow_runs.states import ACTIVE_STATUSES

    if row.run_id and (run is None or run.status not in ACTIVE_STATUSES):
        return False
    return row.source != "seat_required" or (run is not None and seat_paused(run))


async def pool_entries(db: AsyncSession, user: User, *, workspace_id: str | None = None,
                       runnable_only: bool = False) -> list[dict[str, Any]]:
    query = (select(SessionHandover, Session).join(Session, Session.id == SessionHandover.session_id)
             .where(SessionHandover.status == STATUS_PENDING, SessionHandover.to_user_id.is_(None),
                    Session.project_id.in_(select(UserProject.project_id).where(UserProject.user_id == user.id)),
                    outside_foreign_private(Session.project_id, user.id))
             .order_by(SessionHandover.created_at.desc()).limit(100))
    if workspace_id:
        query = query.where(Session.project_id == workspace_id)
    entries = []
    for row, session in (await db.execute(query)).all():
        run = await db.get(WorkflowRun, row.run_id) if row.run_id else None
        if not _still_open(row, run):
            continue
        runnable = await can_run_now(db, user, row.needs, session.project_id)
        if runnable or not runnable_only:
            entries.append(pool_view(row, session, run, can_run_now=runnable))
    return entries


def pool_view(row: SessionHandover, session: Session, run: WorkflowRun | None, *, can_run_now: bool) -> dict[str, Any]:
    from ..workflow_runs.states import STATUS_PAUSED

    state = (f"paused: {run.pause_reason}" if run.status == STATUS_PAUSED else run.status) if run is not None else ""
    return {"id": row.id, "session_id": session.id, "workspace_id": session.project_id, "run_id": row.run_id,
            "title": (run.title if run is not None else "") or dict(session.metadata_ or {}).get("title") or "Session",
            "repository": run.repository if run is not None else None, "needs": dict(row.needs or {}),
            "state": state, "last_step": run.current_node_id if run is not None else None,
            "summary": row.context_summary or row.reason, "source": row.source, "from_user_id": row.from_user_id,
            "created_at": row.created_at.isoformat() if row.created_at else None, "can_run_now": can_run_now}


__all__ = ["can_run_now", "entry_needs", "is_member", "pool_entries", "pool_view"]
