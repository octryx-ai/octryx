"""Pool turns: a free runner, else (chat sends) a ``waiting_runner`` job without a device that a pool runner's tick
takes, oldest first, one person in one Workspace per runner. The owner's Stop cancels the wait."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Message, Session, UserDevice
from ...time_utils import utc_now
from ..data_access import as_viewer
from .chat_turn import (
    DeviceTurnRefusal,
    DeviceTurnStarted,
    admitted_target,
    new_thread,
    pool_default_model,
    record_target,
    store_prompt,
)
from .contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION
from .job_state import STATUS_OFFERED, STATUS_REJECTED, STATUS_WAITING, DeviceJobError, _audit
from .jobs import start_turn, wait_for_runner
from .runner_pool import (
    POOL_DEVICE_ID,
    REASON_POOL_EMPTY,
    REASON_POOL_FORBIDDEN,
    PoolChoice,
    can_take,
    is_pool_runner,
    new_folder,
    pool_allowed,
    previous_pool_target,
    resolve_runner,
)
from .turn_engine import require_engine

_SCAN = 50


async def pool_turn_runner(
    db: AsyncSession, *, user_id: str, existing: Session | str, prompt: str, model: str, permission_mode: str,
    effort: str, wait: bool, rerun_message: Message | None, idempotency_key: str | None,
) -> PoolChoice | DeviceTurnStarted | DeviceTurnRefusal:
    workspace_id = existing.project_id if isinstance(existing, Session) else existing
    previous = previous_pool_target(existing if isinstance(existing, Session) else None)
    choice = await resolve_runner(db, workspace_id=workspace_id, owner_user_id=user_id, previous=previous)
    if choice == REASON_POOL_EMPTY and wait:
        return await _queue_turn(db, user_id=user_id, existing=existing, prompt=prompt, model=model,
                                 permission_mode=permission_mode, effort=effort, previous=previous,
                                 rerun_message=rerun_message, idempotency_key=idempotency_key)
    if isinstance(choice, str):
        forbidden = choice == REASON_POOL_FORBIDDEN
        return DeviceTurnRefusal(STATE_DENIED if forbidden else STATE_NEEDS_CONFIGURATION, choice,
                                 403 if forbidden else 409)
    return choice


async def _queue_turn(
    db: AsyncSession, *, user_id: str, existing: Session | str, prompt: str, model: str, permission_mode: str,
    effort: str, previous: dict[str, Any] | None, rerun_message: Message | None, idempotency_key: str | None,
) -> DeviceTurnStarted | DeviceTurnRefusal:
    thread = existing if isinstance(existing, Session) else await new_thread(
        db, user_id=user_id, project_id=existing, prompt=prompt)
    try:
        job = await wait_for_runner(db, owner_user_id=user_id, session_id=thread.id, workspace_id=thread.project_id,
                                    prompt=prompt, model=model, permission_mode=permission_mode, effort=effort)
    except DeviceJobError as error:
        return DeviceTurnRefusal(error.state, error.reason, error.status)
    prompt = await store_prompt(db, thread, job, prompt, rerun_message=rerun_message, message_on_accept=False,
                                idempotency_key=idempotency_key, author_user_id=user_id)
    job.turn_prompt = prompt
    record_target(thread, device_id=str((previous or {}).get("device_id") or POOL_DEVICE_ID),
                  folder=str((previous or {}).get("folder") or ""), profile="governed", model=model,
                  permission_mode=permission_mode, effort=effort, prompt=prompt, pool=True)
    await db.flush()
    return DeviceTurnStarted(session=thread, job_id=job.id)


async def claim_waiting(db: AsyncSession, device: UserDevice | None) -> list[DeviceJob]:
    if device is None or not await is_pool_runner(db, device):
        return []
    # Read and claimed past the viewer filter, like the runner's tenancy (``runner_tenant``): an idle runner's tick
    # reads as nobody, and a waiting turn may lie in its owner's private Workspace. It is admitted as that owner.
    table = DeviceJob.__table__
    connection = await db.connection()
    waiting = (await connection.execute(
        select(table.c.id, table.c.owner_user_id, table.c.workspace_id).where(table.c.status == STATUS_WAITING)
        .order_by(table.c.created_at, table.c.id).limit(_SCAN))).all()
    taken: list[DeviceJob] = []
    for job_id, owner, workspace in waiting:
        with as_viewer(owner):
            if not await can_take(db, device, owner_user_id=owner, workspace_id=workspace):
                continue
            job = await db.get(DeviceJob, job_id)
            admission = await _admit(db, job, device)  # before the claim: the gate counts the runner's turns
            # Another runner's tick may take the same turn: whoever moves it off waiting first has it. Its turn is
            # sent only once start_turn marks it pending.
            moved = await connection.execute(update(table).where(
                table.c.id == job_id, table.c.status == STATUS_WAITING).values(status=STATUS_OFFERED,
                                                                               device_id=device.id))
            if moved.rowcount != 1:
                continue
            await db.refresh(job)
            if isinstance(admission, str):
                _reject(db, job, admission)
            else:
                await _start(db, job, device, *admission)
            await db.flush()  # the next turn's raw tenancy read sees this one's outcome
            taken.append(job)
    from .jobs_channel import publish  # noqa: PLC0415

    for job in taken:
        await publish(job, {"eventType": "job_rejected" if job.status == STATUS_REJECTED else "turn_offered"},
                      device_name=device.name or "")
    return taken


async def _admit(db: AsyncSession, job: DeviceJob, device: UserDevice) -> tuple[Session, str, str, Any] | str:
    thread = await db.get(Session, job.session_id)
    if thread is None:
        return "session_not_found"
    if not await pool_allowed(db, thread.project_id):
        return REASON_POOL_FORBIDDEN
    previous = previous_pool_target(thread) or {}
    folder = str(previous.get("folder") or "") if previous.get("device_id") == device.id else ""
    folder = folder or new_folder()
    model = job.turn_model or await pool_default_model(db, user_id=job.owner_user_id,
                                                       workspace_id=thread.project_id, device_id=device.id)
    admitted = await admitted_target(db, user_id=job.owner_user_id, existing=thread, workspace_id=thread.project_id,
                                     device_id=device.id, folder=folder, profile=job.profile, model=model)
    if isinstance(admitted, DeviceTurnRefusal):
        return admitted.reason
    decision, model = admitted
    return thread, folder, model, decision


async def _start(db: AsyncSession, job: DeviceJob, device: UserDevice, thread: Session, folder: str, model: str,
                 decision: Any) -> None:
    permission_mode, effort = job.turn_permission_mode or "", job.turn_effort or ""
    try:
        async with db.begin_nested():
            await start_turn(db, owner_user_id=job.owner_user_id, device=device, session_id=thread.id,
                             workspace_id=thread.project_id, folder=folder, profile=job.profile,
                             prompt=job.turn_prompt or "", policy_decision_id=decision.policy_decision_id,
                             model=model, permission_mode=permission_mode, effort=effort, waiting=job)
            await require_engine(db, device, job)
    except DeviceJobError as error:
        await db.refresh(job)
        _reject(db, job, error.reason)
        return
    record_target(thread, device_id=device.id, folder=folder, profile=job.profile, model=model,
                  permission_mode=permission_mode, effort=effort, prompt=job.turn_prompt or "", pool=True)


def _reject(db: AsyncSession, job: DeviceJob, reason: str) -> None:
    job.status, job.status_reason, job.finished_at = STATUS_REJECTED, reason, utc_now()
    _audit(db, actor_id=job.owner_user_id, action="device.job.rejected", job=job, details={"reason": reason})


__all__ = ["claim_waiting", "pool_turn_runner"]
