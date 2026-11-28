"""The ``/chat/api/send`` adapter for a device target: service ``services/devices/chat_turn``."""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Message, Session, User
from ...services.devices.chat_turn import DeviceTurnRefusal, device_thread_target, start_device_turn
from ...services.devices.jobs_channel import publish
from .chat_turn_ack_state import _build_chat_turn_ack_state


async def send_target(db: AsyncSession, payload) -> dict:
    # The message's own device, else where its thread runs; a run's thread never leaves its run's target.
    from ...services.devices.agent_runtime import chat_target_for
    from ...services.workflow_runs.runtime_target.send_guard import send_refusal

    named = payload.execution_target
    target = named.model_dump() if named is not None and named.kind == "device" else await chat_target_for(
        db, payload.session_id)
    if (refused := await send_refusal(db, session_id=payload.session_id, device_target=target)) is not None:
        raise HTTPException(status_code=409, detail=refused)
    return target


async def device_chat_send(request: Request, db: AsyncSession, *, user: User, payload,
                           target: dict, project_id: str | None = None) -> JSONResponse:
    # A message naming its own device names no Server model too (refused, never ignored); a derived target ignores the
    # Server model picker, which has nothing to choose there.
    named = payload.execution_target is not None and payload.execution_target.kind == "device"
    from ...services.session.turn_handoff import names_a_workflow

    workflow = payload.workflow_key if names_a_workflow(payload.workflow_key, payload.workflow_decisions) else ""
    selections = {"runtime_target_id": payload.runtime_target_id, "workflow_key": workflow} if named else None
    return await device_chat_turn(request, db, user=user, prompt=payload.prompt, target=target,
                                  session_id=payload.session_id, project_id=project_id or payload.project_id,
                                  idempotency_key=payload.idempotency_key, thinking_level=payload.thinking_level,
                                  server_selections=selections)


async def device_chat_turn(request: Request, db: AsyncSession, *, user: User, prompt: str, target: dict,
                           session_id: str | None, project_id: str | None, idempotency_key: str | None = None,
                           thinking_level: str | None = None,
                           server_selections: dict[str, str] | None = None) -> JSONResponse:
    from ...services.devices.runner_pool import person_chat_target

    started = await start_device_turn(db, user_id=user.id, prompt=prompt, target=await person_chat_target(db, target),
                                      session_id=session_id or "", project_id=project_id or "",
                                      idempotency_key=idempotency_key, server_selections=server_selections,
                                      wait_for_runner=True)
    if isinstance(started, DeviceTurnRefusal):
        # Nothing was written for a refused turn; the request session is discarded uncommitted.
        raise HTTPException(status_code=started.status, detail=started.detail())
    await db.commit()
    job = await db.get(DeviceJob, started.job_id)
    await publish(job, {"eventType": "turn_offered"})
    state = await _build_chat_turn_ack_state(
        request, db, user=user, session=started.session, runtime_target_id="",
        thinking_level=thinking_level or "light", agent_id="", agent_type=started.session.agent_type or "",
    )
    return JSONResponse(state)


COMPACT_PROMPT = "/compact"


async def device_chat_compact(request: Request, db: AsyncSession, *, user: User, session: Session) -> JSONResponse:
    # The thread's context is compacted where it runs (``/compact``: Claude Code's command, the launcher's
    # thread/compact/start for Codex); a pool thread goes back to the pool, never to one runner by its id.
    from ...services.devices.agent_runtime import POOL_TARGET

    target = device_thread_target(session)
    if target is None:
        raise HTTPException(status_code=409, detail={"state": "denied", "reason": "not_a_device_thread"})
    if target.get("pool"):
        target = {**POOL_TARGET, "model": target.get("model") or ""}
    started = await start_device_turn(db, user_id=user.id, prompt=COMPACT_PROMPT, target=target,
                                      session_id=session.id)
    if isinstance(started, DeviceTurnRefusal):
        raise HTTPException(status_code=started.status, detail=started.detail())
    await db.commit()
    await publish(await db.get(DeviceJob, started.job_id), {"eventType": "turn_offered"})
    state = await _build_chat_turn_ack_state(request, db, user=user, session=started.session, runtime_target_id="",
                                             thinking_level="light", agent_id="", agent_type=session.agent_type or "")
    return JSONResponse(state)


async def device_chat_rerun(request: Request, db: AsyncSession, *, user: User, session: Session, target_message: Message,
                            prompt: str) -> JSONResponse:
    from ...services.devices.agent_runtime import chat_target_for
    from ._chat_state_builder import _build_chat_state

    target = device_thread_target(session) or await chat_target_for(db, session.id)
    if not str(prompt or "").strip():
        raise HTTPException(status_code=400, detail="Prompt is required")
    from ...services.devices.runner_pool import person_chat_target

    started = await start_device_turn(db, user_id=user.id, prompt=prompt, target=await person_chat_target(db, target),
                                      session_id=session.id, rerun_message=target_message, wait_for_runner=True)
    if isinstance(started, DeviceTurnRefusal):
        raise HTTPException(status_code=started.status, detail=started.detail())
    await db.commit()
    job = await db.get(DeviceJob, started.job_id)
    await publish(job, {"eventType": "turn_offered"})
    return JSONResponse(await _build_chat_state(request, db, user=user, session_id=session.id,
                                                agent_type=started.session.agent_type or ""))
