"""Clarification question service — create, answer, skip, list."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ClarificationQuestion
from ..time_utils import utc_now


async def create_clarification_question(
    db: AsyncSession,
    *,
    session_id: str,
    project_id: str | None,
    run_id: str | None,
    question_id: str,
    question_text: str,
    context_json: dict[str, Any] | None = None,
    requested_by: str,
    priority: str = "medium",
    expires_at: Any | None = None,
) -> ClarificationQuestion:
    # Idempotency: if a question with the same question_id+session_id already exists and is open, return it
    existing = await db.execute(
        select(ClarificationQuestion).where(
            ClarificationQuestion.session_id == session_id,
            ClarificationQuestion.question_id == question_id,
            ClarificationQuestion.status == "open",
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    question = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=project_id,
        run_id=run_id,
        question_id=question_id,
        question_text=question_text,
        context_json=context_json or {},
        status="open",
        priority=priority,
        requested_by=requested_by,
        expires_at=expires_at,
        created_at=utc_now(),
    )
    db.add(question)
    await db.flush()
    from .attention.stream import nudge_after_commit

    nudge_after_commit(db, requested_by, event="question")
    return question


async def answer_clarification_question(
    db: AsyncSession,
    *,
    question_id: str,
    answer_text: str,
    answered_by: str,
) -> ClarificationQuestion:
    question = await db.get(ClarificationQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Clarification question not found")
    if question.status != "open":
        raise HTTPException(status_code=400, detail=f"Question is already {question.status}")

    question.status = "answered"
    question.answer_text = answer_text
    question.answered_by = answered_by
    question.answered_at = utc_now()
    await db.flush()
    return question


async def answer_open_clarification_with_reply(
    db: AsyncSession, *, session_id: str, answered_by: str, reply: str
) -> ClarificationQuestion | None:
    # Only the requester's next message answers; nobody answers on the requester's behalf.
    question = await get_open_clarification_for_session(db, session_id=session_id)
    if question is None or question.status != "open" or not (reply or "").strip():
        return None
    return await answer_clarification_question(
        db, question_id=question.id, answer_text=reply.strip()[:20_000], answered_by=answered_by
    )


async def skip_clarification_question(
    db: AsyncSession,
    *,
    question_id: str,
    skipped_by: str,
    reason: str | None = None,
) -> ClarificationQuestion:
    question = await db.get(ClarificationQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Clarification question not found")
    if question.status != "open":
        raise HTTPException(status_code=400, detail=f"Question is already {question.status}")

    question.status = "skipped"
    question.skipped_by = skipped_by
    question.skipped_at = utc_now()
    if reason:
        question.answer_text = reason  # store skip reason in answer_text for audit
    await db.flush()
    return question


async def cancel_clarification_question(
    db: AsyncSession,
    *,
    question_id: str,
    cancelled_by: str,
) -> ClarificationQuestion:
    # Only the requester or an admin can cancel.
    question = await db.get(ClarificationQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Clarification question not found")
    if question.status != "open":
        raise HTTPException(status_code=400, detail=f"Question is already {question.status}")

    # Only the requester can cancel
    if question.requested_by != cancelled_by:
        raise HTTPException(status_code=403, detail="Only the requester can cancel a clarification question")

    question.status = "cancelled"
    question.skipped_by = cancelled_by  # reuse field — who cancelled
    question.skipped_at = utc_now()
    await db.flush()
    return question


async def get_clarification_by_id(db: AsyncSession, *, question_id: str) -> ClarificationQuestion:
    question = await db.get(ClarificationQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Clarification question not found")
    return question


async def get_open_clarification_for_session(
    db: AsyncSession,
    *,
    session_id: str,
) -> ClarificationQuestion | None:
    result = await db.execute(
        select(ClarificationQuestion)
        .where(
            ClarificationQuestion.session_id == session_id,
            ClarificationQuestion.status.in_(("open", "answered", "skipped")),
        )
        .order_by(ClarificationQuestion.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _outside_private_workspaces():
    from sqlalchemy import or_  # noqa: PLC0415

    from ..models import Project, Session  # noqa: PLC0415

    private_sessions = select(Session.id).join(Project, Project.id == Session.project_id).where(
        Project.access_mode == "private")
    private_projects = select(Project.id).where(Project.access_mode == "private")
    session_outside = or_(ClarificationQuestion.session_id.is_(None),
                          ClarificationQuestion.session_id.not_in(private_sessions))
    project_outside = or_(ClarificationQuestion.project_id.is_(None),
                          ClarificationQuestion.project_id.not_in(private_projects))
    return session_outside & project_outside


async def list_clarification_questions(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ClarificationQuestion]:
    stmt = select(ClarificationQuestion).order_by(ClarificationQuestion.created_at.desc())
    if project_id:
        stmt = stmt.where(ClarificationQuestion.project_id == project_id)
    # Questions of sessions in a private Workspace are their owner's alone; the cross-session
    # list (admins) never shows them. A session's own list is already limited to who may read that session.
    if not session_id:
        stmt = stmt.where(_outside_private_workspaces())
    if session_id:
        stmt = stmt.where(ClarificationQuestion.session_id == session_id)
    if status:
        stmt = stmt.where(ClarificationQuestion.status == status)
    normalized_limit = max(1, min(limit, 200))
    normalized_offset = max(0, offset)
    stmt = stmt.limit(normalized_limit).offset(normalized_offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_clarification_questions(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(ClarificationQuestion)
    if project_id:
        stmt = stmt.where(ClarificationQuestion.project_id == project_id)
    # Questions of sessions in a private Workspace are their owner's alone; the cross-session
    # list (admins) never shows them. A session's own list is already limited to who may read that session.
    if not session_id:
        stmt = stmt.where(_outside_private_workspaces())
    if session_id:
        stmt = stmt.where(ClarificationQuestion.session_id == session_id)
    if status:
        stmt = stmt.where(ClarificationQuestion.status == status)
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def expire_overdue_clarification_questions(db: AsyncSession) -> int:
    now = utc_now()
    stmt = select(ClarificationQuestion).where(
        ClarificationQuestion.status == "open",
        ClarificationQuestion.expires_at.isnot(None),
        ClarificationQuestion.expires_at <= now,
    )
    result = await db.execute(stmt)
    questions = list(result.scalars().all())
    for q in questions:
        q.status = "expired"
        q.skipped_at = now
    if questions:
        await db.flush()
    return len(questions)


def serialize_clarification(question: ClarificationQuestion) -> dict[str, Any]:
    return {
        "id": question.id,
        "session_id": question.session_id,
        "project_id": question.project_id,
        "run_id": question.run_id,
        "question_id": question.question_id,
        "question_text": question.question_text,
        "context_json": dict(question.context_json or {}),
        "status": question.status,
        "priority": question.priority,
        "answer_text": question.answer_text,
        "answered_by": question.answered_by,
        "answered_at": question.answered_at.isoformat() if question.answered_at else None,
        "skipped_by": question.skipped_by,
        "skipped_at": question.skipped_at.isoformat() if question.skipped_at else None,
        "requested_by": question.requested_by,
        "expires_at": question.expires_at.isoformat() if question.expires_at else None,
        "created_at": question.created_at.isoformat() if question.created_at else None,
    }
