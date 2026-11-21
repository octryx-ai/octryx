from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ConflictError
from app.exceptions.api import ValidationError as DomainValidationError
from app.exceptions.base import NotFoundError

from ...db import get_db
from ...models import User
from ...schemas.operations.session import MessageResponse, SessionCreate, SessionHandoverResponse, SessionResponse
from ...services.auth import get_current_user
from ...services.session.analysis_export import build_session_analysis_export
from ...services.session.api import (
    create_session_response,
    get_session_messages_response,
    get_session_response,
    list_session_responses,
)
from ...services.session.collaboration import list_session_handovers
from ...services.session.feedback import SessionFeedbackRefusedError
from ...services.session.pdf_export import build_session_pdf_export
from ._session_api_helpers import FeedbackCreate, FeedbackResponse, get_message_feedback, submit_message_feedback
from ._sessions_coordinator_routes import router as coordinator_router
from ._sessions_sharing_routes import router as sharing_router
from ._sessions_turn_routes import router as turn_router

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])
router.include_router(coordinator_router)
router.include_router(turn_router)


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_session_responses(db=db, user_id=current_user.id)


# Static handover listing must be registered before the dynamic `/{session_id}`
# route, otherwise FastAPI resolves `/handovers` as `session_id="handovers"`.
@router.get("/handovers", response_model=list[SessionHandoverResponse])
async def get_session_handovers(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_session_handovers(db, current_user=current_user, status_filter=(status or "").strip() or None)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_session_response(db=db, session_id=session_id, user_id=current_user.id)


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_session_messages_response(db=db, session_id=session_id, user_id=current_user.id)


@router.get("/{session_id}/export.pdf")
async def export_session_pdf(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    export = await build_session_pdf_export(
        db,
        session_id=session_id,
        user_id=current_user.id,
        exported_by=current_user,
    )
    headers = {"Content-Disposition": f'attachment; filename="{export.filename}"'}
    return Response(content=export.content, media_type="application/pdf", headers=headers)


@router.get("/{session_id}/export.analysis.json")
async def export_session_analysis_json(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    export = await build_session_analysis_export(
        db,
        session_id=session_id,
        user_id=current_user.id,
        exported_by=current_user,
    )
    headers = {"Content-Disposition": f'attachment; filename="{export.filename}"'}
    return Response(content=export.content, media_type="application/json; charset=utf-8", headers=headers)


@router.post("", response_model=SessionResponse)
async def create_session(
    body: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_session_response(
        db=db,
        user_id=current_user.id,
        project_id=body.project_id,
        agent_type=body.agent_type,
    )


@router.post("/{session_id}/messages/{message_id}/feedback", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    session_id: str,
    message_id: str,
    body: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rate an agent answer: good or bad, what was good, what was not good, and marked aspects.

    Kept in the Workspace's Memory lobe (``knowledge_answer_feedback``); re-submitting replaces it.
    """
    try:
        return await submit_message_feedback(
            db, session_id=session_id, message_id=message_id, body=body, user_id=current_user.id
        )
    except SessionFeedbackRefusedError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc))
    except DomainValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{session_id}/messages/{message_id}/feedback", response_model=FeedbackResponse | None)
async def get_feedback(
    session_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's feedback for a message, or null if not yet rated."""
    try:
        return await get_message_feedback(
            db,
            session_id=session_id,
            message_id=message_id,
            user_id=current_user.id,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Session not found")


# Included after the routes above so the registration order stays the same.
router.include_router(sharing_router)
