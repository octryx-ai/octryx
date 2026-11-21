"""The ``/chat/api/send`` adapter for a device target: service ``services/devices/chat_turn``.

A refusal keeps the chat HTTP contract (``HTTPException`` with ``detail {state, reason, code}``); a started turn
answers the same chat state as a server turn, and the chat follows the job over ``device_job_event``.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Message, Session, User
from ...services.devices.chat_turn import DeviceTurnRefusal, device_thread_target, start_device_turn
from ...services.devices.jobs_channel import publish
from .chat_turn_ack_state import _build_chat_turn_ack_state


async def refuse_runtime_mismatch(db: AsyncSession, payload) -> None:
    """A message on a workflow run's thread runs where the run runs (``workflow_runs.runtime_target.send_guard``)."""
    from ...services.workflow_runs.runtime_target.send_guard import send_refusal

    target = payload.execution_target
    device = target.model_dump() if target is not None and target.kind == "device" else None
    if (refused := await send_refusal(db, session_id=payload.session_id, device_target=device)) is not None:
        raise HTTPException(status_code=409, detail=refused)


async def device_chat_send(request: Request, db: AsyncSession, *, user: User, payload) -> JSONResponse:
    target = payload.execution_target.model_dump()
    started = await start_device_turn(
        db, user_id=user.id, prompt=payload.prompt, target=target, session_id=payload.session_id,
        project_id=payload.project_id, idempotency_key=payload.idempotency_key,
        server_selections={"workflow_key": payload.workflow_key, "runtime_target_id": payload.runtime_target_id},
    )
    if isinstance(started, DeviceTurnRefusal):
        # Nothing was written for a refused turn; the request session is discarded uncommitted.
        raise HTTPException(status_code=started.status, detail=started.detail())
    await db.commit()
    job = await db.get(DeviceJob, started.job_id)
    await publish(job, {"eventType": "turn_offered"})
    state = await _build_chat_turn_ack_state(
        request, db, user=user, session=started.session, runtime_target_id="",
        thinking_level=payload.thinking_level or "light", agent_id="", agent_type=started.session.agent_type or "",
    )
    return JSONResponse(state)


async def device_chat_rerun(request: Request, db: AsyncSession, *, user: User, session: Session, target_message: Message,
                            prompt: str) -> JSONResponse | None:
    """Retry or edit-and-rerun on a device thread runs on that device again (never the server path).

    None for a Server thread. The rerun takes the thread's recorded target (device, folder, profile, model); the
    device gate decides again, and a refusal keeps the history and answers the same detail as a device send.
    """
    from ._chat_state_builder import _build_chat_state

    target = device_thread_target(session)
    if target is None:
        return None
    if not str(prompt or "").strip():
        raise HTTPException(status_code=400, detail="Prompt is required")
    started = await start_device_turn(
        db, user_id=user.id, prompt=prompt, target=target, session_id=session.id, rerun_message=target_message)
    if isinstance(started, DeviceTurnRefusal):
        raise HTTPException(status_code=started.status, detail=started.detail())
    await db.commit()
    job = await db.get(DeviceJob, started.job_id)
    await publish(job, {"eventType": "turn_offered"})
    return JSONResponse(await _build_chat_state(request, db, user=user, session_id=session.id,
                                                agent_type=started.session.agent_type or ""))
