"""Chat rerun routes: rerun a turn from a message, tool call, approval or change preview.

Included by ``chat_sessions_actions.router``.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.admin.admin_panel._chat import ChatMessageRerunRequest
from app.services.session.turn_tasks import effective_session_status as _effective_session_status

from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY
from ...db import async_session_factory, get_db
from ...models import (
    Approval,
    ChangePreview,
    Message,
    ToolCall,
)
from ...models import (
    Session as AgentSession,
)
from ...services.chat_rerun import (
    resolve_chat_rerun_target_message,
    resolve_chat_rerun_target_message_for_approval,
    resolve_chat_rerun_target_message_for_change_preview,
    resolve_chat_rerun_target_message_for_tool_call,
)
from ...services.session.turn_launch import start_chat_rerun_turn
from .._helpers._chat_state_builder import _build_chat_state
from .._helpers.api_guards import _require_api_user
from .._helpers.chat_device_turn import device_chat_rerun

router = APIRouter()


async def _start_rerun_from_target_message(
    *,
    request: Request,
    db: AsyncSession,
    user,
    session: AgentSession,
    target_message: Message,
    prompt: str,
) -> JSONResponse:
    # A device thread reruns on its device; only a Server thread takes the server turn path.
    if (device_rerun := await device_chat_rerun(request, db, user=user, session=session,
                                                target_message=target_message, prompt=prompt)) is not None:
        return device_rerun
    request_session_factory = getattr(request.app.state, "async_session_factory", async_session_factory)
    rerun_session = await start_chat_rerun_turn(
        db,
        user_id=user.id,
        session_factory=request_session_factory,
        session=session,
        message=target_message,
        prompt=prompt,
    )
    state = await _build_chat_state(
        request,
        db,
        user=user,
        session_id=rerun_session.id,
        agent_type=rerun_session.agent_type or DEFAULT_AGENT_MODE_KEY,
    )
    return JSONResponse(state)


@router.post("/chat/api/sessions/{session_id}/messages/{message_id}/rerun")
async def chat_message_rerun_api(
    session_id: str,
    message_id: str,
    request: Request,
    payload: ChatMessageRerunRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if _effective_session_status(session) == "archived":
        raise HTTPException(status_code=409, detail="Archived: restore it from Archived chats in the list")
    if _effective_session_status(session) == "running":
        raise HTTPException(status_code=409, detail="This thread is already running")

    message = (
        await db.execute(select(Message).where(Message.id == message_id, Message.session_id == session.id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    try:
        target_message = await resolve_chat_rerun_target_message(
            db,
            session=session,
            message=message,
        )
        return await _start_rerun_from_target_message(
            request=request,
            db=db,
            user=user,
            session=session,
            target_message=target_message,
            prompt=payload.prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chat/api/sessions/{session_id}/tool-calls/{tool_call_id}/rerun")
async def chat_tool_call_rerun_api(
    session_id: str,
    tool_call_id: str,
    request: Request,
    payload: ChatMessageRerunRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if _effective_session_status(session) == "archived":
        raise HTTPException(status_code=409, detail="Archived: restore it from Archived chats in the list")
    if _effective_session_status(session) == "running":
        raise HTTPException(status_code=409, detail="This thread is already running")

    tool_call = (
        await db.execute(select(ToolCall).where(ToolCall.id == tool_call_id, ToolCall.session_id == session.id))
    ).scalar_one_or_none()
    if tool_call is None:
        raise HTTPException(status_code=404, detail="Tool call not found")

    try:
        target_message = await resolve_chat_rerun_target_message_for_tool_call(
            db,
            session=session,
            tool_call=tool_call,
        )
        return await _start_rerun_from_target_message(
            request=request,
            db=db,
            user=user,
            session=session,
            target_message=target_message,
            prompt=payload.prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chat/api/sessions/{session_id}/approvals/{approval_id}/rerun")
async def chat_approval_rerun_api(
    session_id: str,
    approval_id: str,
    request: Request,
    payload: ChatMessageRerunRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if _effective_session_status(session) == "archived":
        raise HTTPException(status_code=409, detail="Archived: restore it from Archived chats in the list")
    if _effective_session_status(session) == "running":
        raise HTTPException(status_code=409, detail="This thread is already running")

    approval = (
        await db.execute(select(Approval).where(Approval.id == approval_id, Approval.session_id == session.id))
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    try:
        target_message = await resolve_chat_rerun_target_message_for_approval(
            db,
            session=session,
            approval=approval,
        )
        return await _start_rerun_from_target_message(
            request=request,
            db=db,
            user=user,
            session=session,
            target_message=target_message,
            prompt=payload.prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chat/api/sessions/{session_id}/change-previews/{change_preview_id}/rerun")
async def chat_change_preview_rerun_api(
    session_id: str,
    change_preview_id: str,
    request: Request,
    payload: ChatMessageRerunRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if _effective_session_status(session) == "archived":
        raise HTTPException(status_code=409, detail="Archived: restore it from Archived chats in the list")
    if _effective_session_status(session) == "running":
        raise HTTPException(status_code=409, detail="This thread is already running")

    change_preview = (
        await db.execute(
            select(ChangePreview).where(ChangePreview.id == change_preview_id, ChangePreview.session_id == session.id)
        )
    ).scalar_one_or_none()
    if change_preview is None:
        raise HTTPException(status_code=404, detail="Change preview not found")

    try:
        target_message = await resolve_chat_rerun_target_message_for_change_preview(
            db,
            session=session,
            change_preview=change_preview,
        )
        return await _start_rerun_from_target_message(
            request=request,
            db=db,
            user=user,
            session=session,
            target_message=target_message,
            prompt=payload.prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
