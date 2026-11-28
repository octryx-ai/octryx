"""Agent turns without a device of their own run on the server runners (the pool): chat, ``/api/v1`` and channel
turns, scheduled tasks, and the turns of a workflow run the server runs."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Message
from .chat_turn import DeviceTurnRefusal, start_device_turn
from .job_state import BUSY_STATUSES

POOL_TARGET: dict[str, Any] = {"kind": "device", "device_id": "pool", "profile": "governed"}
POOL_RUNTIME_LABEL = "server_runner_pool"
TURN_WAIT_SECONDS = 600
TASK_WAIT_SECONDS = 3600  # a scheduled task may work longer than a person waits
_POLL_SECONDS = 1.0


async def chat_target_for(db: AsyncSession, session_id: str | None) -> dict[str, Any]:
    # A thread that follows a workflow run runs where its run runs; every other turn runs on the pool.
    from ..workflow_runs.records import active_run_for_session
    from ..workflow_runs.runtime_target.target import KIND_DEVICE, stored_target

    run = await active_run_for_session(db, session_id) if session_id else None
    target = stored_target(run)
    if target is not None and target["kind"] == KIND_DEVICE:
        return {key: value for key, value in target.items() if key not in ("chosen_by", "at", "resolved_from")}
    return dict(POOL_TARGET)


@dataclass(frozen=True)
class PoolTurn:
    session_id: str
    job_id: str
    user_message_id: str
    state: str  # done | failed | timeout
    answer: str


async def run_pool_turn(db: AsyncSession, *, user_id: str, prompt: str, session_id: str = "",
                        project_id: str = "", timeout: float = TURN_WAIT_SECONDS, target: dict[str, Any] | None = None,
                        rerun_message: Message | None = None, person_chat: bool = False
                        ) -> PoolTurn | DeviceTurnRefusal:
    from .jobs_channel import publish
    from .runner_pool import person_chat_target

    target = target or dict(POOL_TARGET)
    target = await person_chat_target(db, target) if person_chat else target
    started = await start_device_turn(db, user_id=user_id, prompt=prompt, target=target, session_id=session_id,
                                      project_id=project_id, rerun_message=rerun_message, wait_for_runner=True)
    if isinstance(started, DeviceTurnRefusal):
        return started
    session_id = started.session.id
    asked = (await db.execute(select(Message.id).where(Message.session_id == session_id, Message.role == "user")
                              .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()
    await db.commit()
    await publish(await db.get(DeviceJob, started.job_id), {"eventType": "turn_offered"})
    state = await _wait(db, started.job_id, timeout)
    answer = await _answer(db, started.job_id) if state == "done" else ""
    return PoolTurn(session_id, started.job_id, str(asked or ""), state, answer)


async def _wait(db: AsyncSession, job_id: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        query = select(DeviceJob.status, DeviceJob.status_reason).where(DeviceJob.id == job_id)
        row = (await db.execute(query)).first()
        await db.commit()  # the next read sees what the channel committed meanwhile
        if row is None:
            return "failed"
        if row[0] not in BUSY_STATUSES:
            return "failed" if row[1] else "done"
        await asyncio.sleep(_POLL_SECONDS)
    return "timeout"


async def _answer(db: AsyncSession, job_id: str) -> str:
    from .run_trace import device_answer_key

    job = await db.get(DeviceJob, job_id)
    await db.refresh(job)
    message = (await db.execute(select(Message).where(Message.idempotency_key == device_answer_key(job))
                                .order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none()
    return str(message.content or "") if message is not None else ""


class PoolTaskError(RuntimeError):
    pass  # a scheduled task's runner turn was refused or did not finish: the task run fails with its reason


async def run_task_on_pool(db: AsyncSession, *, task: Any, session: Any, prompt: str, user_id: str) -> dict[str, Any]:
    # A workflow Action's run runs where its target resolved (the pool, ``runtime_target.target``): its phases are
    # runner turns of their own, so the scheduler runs no turn for it. Any other task is one runner turn.
    from ..workflow_runs.automation import action_run_config
    from ..workflow_runs.records import active_run_for_session

    if action_run_config(task) is not None:
        run = await active_run_for_session(db, session.id)
        if run is None:
            raise PoolTaskError("action_workflow_run_missing")
        return {"session_id": session.id, "workflow_run_id": run.id, "runtime": POOL_RUNTIME_LABEL}
    turn = await runner_turn(db, user_id=user_id, prompt=prompt, session_id=session.id)
    return {"session_id": session.id, "response": turn.answer, "job_id": turn.job_id, "runtime": POOL_RUNTIME_LABEL}


async def runner_turn(db: AsyncSession, *, user_id: str, prompt: str, session_id: str,
                      timeout: float = TASK_WAIT_SECONDS) -> PoolTurn:
    # A background turn (a scheduled task or its step, a chain step, a follow-up) where its session runs, awaited.
    turn = await run_pool_turn(db, user_id=user_id, prompt=prompt, session_id=session_id, timeout=timeout,
                               target=await chat_target_for(db, session_id))
    if isinstance(turn, DeviceTurnRefusal):
        raise PoolTaskError(turn.reason)
    if turn.state != "done":
        raise PoolTaskError(f"pool_turn_{turn.state}")
    return turn


APPROVED_PROMPT = ("The person approved approval {approval_id} ({action}) in Octryx. Repeat exactly the same call "
                   "now, with the same arguments.")
REJECTED_PROMPT = ("The person rejected approval {approval_id} ({action}) in Octryx: {reason}. Do not repeat the call; "
                   "tell the person what was not done.")


async def resume_device_thread(db: AsyncSession, *, session: Any, approval: Any, decision: str) -> bool:
    # A decided approval of a device or runner thread continues it there, as a paused platform turn would resume:
    # the next turn repeats the approved call (or reports the rejection).
    from .chat_turn import device_thread_target

    target = device_thread_target(session)
    if target is None or decision not in ("approved", "rejected"):
        return False
    if target.get("pool"):
        target = {**POOL_TARGET, "model": target.get("model") or ""}
    template = APPROVED_PROMPT if decision == "approved" else REJECTED_PROMPT
    prompt = template.format(approval_id=approval.id, action=str(approval.action or "").strip(),
                             reason=str(approval.reason or "no reason given").strip())
    started = await start_device_turn(db, user_id=str(session.user_id), prompt=prompt, target=target,
                                      session_id=session.id)
    if isinstance(started, DeviceTurnRefusal):
        return False
    from .jobs_channel import publish

    await db.commit()
    await publish(await db.get(DeviceJob, started.job_id), {"eventType": "turn_offered"})
    return True


async def stop_session_jobs(db: AsyncSession, *, session_id: str, actor_id: str) -> int:
    # The chat's Stop ends the thread's running device turn too, or its wait for a runner.
    from .jobs import request_stop

    jobs = (await db.execute(select(DeviceJob).where(DeviceJob.session_id == session_id,
                                                     DeviceJob.owner_user_id == actor_id,
                                                     DeviceJob.status.in_(BUSY_STATUSES)))).scalars().all()
    for job in jobs:
        await request_stop(db, job, actor_id=actor_id)
    return len(jobs)


__all__ = ["POOL_TARGET", "PoolTurn", "chat_target_for",
           "PoolTaskError", "run_pool_turn", "run_task_on_pool", "runner_turn", "stop_session_jobs"]
