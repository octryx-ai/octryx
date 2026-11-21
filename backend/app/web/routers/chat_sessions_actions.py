"""Chat session action and feedback routes; the rerun routes are included from ``chat_rerun_actions``."""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ConflictError, ValidationError
from app.exceptions.base import NotFoundError
from app.schemas.admin.admin_panel._chat import ChatRenameRequest, MessageFeedbackRequest

from ...db import get_db
from ...models import (
    Session as AgentSession,
)
from ...services.session.feedback import SessionFeedbackRefusedError, submit_session_message_feedback
from ...services.session.session_title import apply_user_title
from .._helpers._chat_state_builder import _build_chat_state
from .._helpers.api_guards import _require_api_user
from .._helpers.chat_turn_start import _chat_generate_task_impl
from .chat_rerun_actions import router as chat_rerun_actions_router

router = APIRouter()


@router.post("/chat/api/sessions/{session_id}/rename")
async def chat_rename_session_api(
    session_id: str,
    request: Request,
    payload: ChatRenameRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = dict(session.metadata_ or {})
    if apply_user_title(metadata, payload.title):
        session.metadata_ = metadata
        await db.commit()

    state = await _build_chat_state(request, db, user=user, session_id=session.id)
    return JSONResponse(state)


@router.post("/chat/api/sessions/{session_id}/generate-task")
async def chat_generate_task(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    import traceback as _traceback

    try:
        return await _chat_generate_task_impl(session_id, request, db)
    except HTTPException:
        raise
    except Exception as _exc:
        _tb = _traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"{type(_exc).__name__}: {_exc}\n\n{_tb}") from _exc


@router.post("/chat/api/sessions/{session_id}/messages/{message_id}/feedback")
async def chat_message_feedback_api(
    session_id: str,
    message_id: str,
    request: Request,
    payload: MessageFeedbackRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    try:
        await submit_session_message_feedback(
            db,
            session_id=session_id,
            message_id=message_id,
            rating=payload.rating,
            liked=payload.liked,
            disliked=payload.disliked,
            aspects=payload.aspects,
            user_id=user.id,
        )
    except SessionFeedbackRefusedError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = await _build_chat_state(request, db, user=user, session_id=session_id)
    return JSONResponse(state)


router.include_router(chat_rerun_actions_router)
