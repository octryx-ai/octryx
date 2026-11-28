"""A workflow run moves with its chat thread when the thread changes hands (``session.handovers``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ...models.session.session_collaboration import SessionHandover
from .records import WorkflowRunError, record_event
from .states import ACTIVE_STATUSES


async def check_handover_request(db: AsyncSession, run: WorkflowRun, *, user: User, receiver: User | None) -> None:
    from ..admin.governance.admin_access_service import is_global_admin
    from .access import run_access

    if run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("not_active", "The run has already ended.")
    if user.id != run.requested_by and not await is_global_admin(db, user.id):
        raise WorkflowRunError("not_requester", "Only the run's requester or an admin hands it over.", 403)
    if receiver is not None and await run_access(db, run, receiver) == "none":
        raise WorkflowRunError("handover_receiver_not_member", "The receiver is not a member of this Workspace.", 422)


def note_handover(db: AsyncSession, run: WorkflowRun, kind: str, *, actor_id: str, detail: dict[str, Any]) -> None:
    record_event(db, run, f"handover_{kind}", node_id=run.current_node_id, actor_id=actor_id, detail=detail)


async def _default_target(db: AsyncSession, run: WorkflowRun, row: SessionHandover, user: User) -> dict[str, Any]:
    from ..devices.seat_engines import PROFILE_SEAT
    from .runtime_target.seat_required import takeover_default
    from .runtime_target.target import KIND_SERVER, target_options

    if dict(row.needs or {}).get("profile") != PROFILE_SEAT:
        return {"kind": KIND_SERVER}
    options = await target_options(db, user=user)
    key = await takeover_default(db, run, options)
    chosen = next((option["target"] for option in options if option["key"] == key), None)
    if chosen is None:
        raise WorkflowRunError("no_seat_device_online", "None of your devices with this engine's seat is online.", 409)
    return chosen


async def move_run(db: AsyncSession, run: WorkflowRun, row: SessionHandover, *, user: User,
                   runtime_target: Any = None) -> None:
    from .records import lock_run
    from .runtime_target.switch import change_runtime

    run = await lock_run(db, run)
    if run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("not_active", "The run has already ended.")
    previous = run.requested_by
    run.requested_by = user.id
    if run.responsible_user_id in (None, previous):
        run.responsible_user_id, run.responsible_source = user.id, "accepted"
    raw = runtime_target or await _default_target(db, run, row, user)
    await change_runtime(db, run, user=user, raw=raw)
    note_handover(db, run, "accepted", actor_id=user.id, detail={"from": previous, "to": user.id})


__all__ = ["check_handover_request", "move_run", "note_handover"]
