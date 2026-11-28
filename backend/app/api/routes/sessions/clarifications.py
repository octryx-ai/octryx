from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import ClarificationQuestion
from ....models.security.user import User
from ....schemas.core.workspace_ref import OptionalWorkspaceId
from ....services.access_control import require_project_access
from ....services.auth import get_current_user
from ....services.clarification_service import (
    answer_clarification_question,
    cancel_clarification_question,
    count_clarification_questions,
    create_clarification_question,
    get_open_clarification_for_session,
    list_clarification_questions,
    serialize_clarification,
    skip_clarification_question,
)
from ....services.session.resource_access import (
    require_matching_project,
    require_record_access,
    require_session_resource_access,
)

router = APIRouter(prefix="/api/v1/clarifications", tags=["clarifications"])

CLARIFICATION_NOT_FOUND_DETAIL = "Clarification question not found"


async def _require_list_scope(db: AsyncSession, *, session_id: str | None, user: User) -> None:
    # A session's questions for whoever may read the session; the cross-session list for admins only.
    if session_id:
        await require_session_resource_access(db, session_id=session_id, user_id=user.id)
        return
    from ....services.admin.governance.admin_access_service import is_global_admin

    if not await is_global_admin(db, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")


async def _accessible_question(db: AsyncSession, question_id: str, user: User, *, require_write: bool):
    question = await db.get(ClarificationQuestion, question_id)
    await require_record_access(
        db, question, user_id=user.id, not_found_detail=CLARIFICATION_NOT_FOUND_DETAIL, require_write=require_write
    )
    return question


class ClarificationCreateRequest(BaseModel):
    session_id: str
    project_id: OptionalWorkspaceId = None
    run_id: str | None = None
    question_id: str
    question_text: str
    context_json: dict | None = None
    priority: str = "medium"


class ClarificationAnswerRequest(BaseModel):
    answer_text: str


class ClarificationSkipRequest(BaseModel):
    reason: str | None = None


class ClarificationResponse(BaseModel):
    id: str
    session_id: str
    project_id: str | None
    run_id: str | None
    question_id: str
    question_text: str
    context_json: dict
    status: str
    priority: str
    answer_text: str | None
    answered_by: str | None
    answered_at: str | None
    skipped_by: str | None
    skipped_at: str | None
    requested_by: str
    expires_at: str | None
    created_at: str


class ClarificationListResponse(BaseModel):
    items: list[ClarificationResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


@router.get("", response_model=ClarificationListResponse)
async def list_clarifications(
    project_id: str | None = Query(None),
    session_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List clarification questions, optionally filtered by project, session, or status."""
    await _require_list_scope(db, session_id=session_id, user=current_user)
    normalized_limit = max(1, min(limit, 200))
    normalized_offset = max(0, offset)
    questions = await list_clarification_questions(
        db,
        project_id=project_id,
        session_id=session_id,
        status=status,
        limit=normalized_limit,
        offset=normalized_offset,
    )
    total = await count_clarification_questions(
        db,
        project_id=project_id,
        session_id=session_id,
        status=status,
    )
    serialized = [ClarificationResponse(**serialize_clarification(q)) for q in questions]
    return ClarificationListResponse(
        items=serialized,
        total=total,
        limit=normalized_limit,
        offset=normalized_offset,
        has_more=(normalized_offset + len(serialized)) < total,
    )


@router.post("", response_model=ClarificationResponse)
async def create_clarification(
    body: ClarificationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new clarification question for a session the caller may write."""
    await require_project_access(db, current_user.id, body.project_id)
    session = await require_session_resource_access(
        db, session_id=body.session_id, user_id=current_user.id, require_write=True
    )
    question = await create_clarification_question(
        db,
        session_id=body.session_id,
        project_id=require_matching_project(session, body.project_id),
        run_id=body.run_id,
        question_id=body.question_id,
        question_text=body.question_text,
        context_json=body.context_json,
        requested_by=current_user.id,
        priority=body.priority,
    )
    await db.commit()
    return ClarificationResponse(**serialize_clarification(question))


@router.get("/{question_id}", response_model=ClarificationResponse)
async def get_clarification(
    question_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single clarification question by ID."""
    question = await _accessible_question(db, question_id, current_user, require_write=False)
    return ClarificationResponse(**serialize_clarification(question))


@router.post("/{question_id}/answer", response_model=ClarificationResponse)
async def answer_clarification(
    question_id: str,
    body: ClarificationAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit an answer to a clarification question. This triggers run resume if applicable."""
    await _accessible_question(db, question_id, current_user, require_write=True)
    question = await answer_clarification_question(
        db,
        question_id=question_id,
        answer_text=body.answer_text,
        answered_by=current_user.id,
    )
    await db.commit()
    return ClarificationResponse(**serialize_clarification(question))


@router.post("/{question_id}/skip", response_model=ClarificationResponse)
async def skip_clarification(
    question_id: str,
    body: ClarificationSkipRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Skip a clarification question. The run continues without the answer."""
    await _accessible_question(db, question_id, current_user, require_write=True)
    question = await skip_clarification_question(
        db,
        question_id=question_id,
        skipped_by=current_user.id,
        reason=body.reason,
    )
    await db.commit()
    return ClarificationResponse(**serialize_clarification(question))


@router.post("/{question_id}/cancel", response_model=ClarificationResponse)
async def cancel_clarification(
    question_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a clarification question. Only the original requester can cancel."""
    await _accessible_question(db, question_id, current_user, require_write=True)
    question = await cancel_clarification_question(
        db,
        question_id=question_id,
        cancelled_by=current_user.id,
    )
    await db.commit()
    return ClarificationResponse(**serialize_clarification(question))


@router.get("/session/{session_id}/open", response_model=ClarificationResponse | None)
async def get_session_open_clarification(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent open/answered/skipped clarification for a session."""
    await require_session_resource_access(db, session_id=session_id, user_id=current_user.id)
    question = await get_open_clarification_for_session(db, session_id=session_id)
    if question is None:
        return None
    return ClarificationResponse(**serialize_clarification(question))
