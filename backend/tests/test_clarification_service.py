"""Unit tests for clarification_service."""

import uuid

import pytest

from app.services.clarification_service import (
    answer_clarification_question,
    cancel_clarification_question,
    create_clarification_question,
    skip_clarification_question,
)


@pytest.mark.asyncio
async def test_create_clarification_question(db, auth_headers):
    session_id = str(uuid.uuid4())
    question = await create_clarification_question(
        db,
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Should we prioritize correctness or speed?",
        context_json={"iteration": 0},
        requested_by="test-user",
        priority="high",
    )
    await db.commit()
    assert question.id is not None
    assert question.session_id == session_id
    assert question.question_id == "scope-missing"
    assert question.status == "open"
    assert question.priority == "high"
    assert question.answer_text is None


@pytest.mark.asyncio
async def test_create_clarification_idempotent_by_question_id_and_session(db, auth_headers):
    session_id = str(uuid.uuid4())
    q1 = await create_clarification_question(
        db,
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Should we prioritize correctness or speed?",
        context_json={},
        requested_by="test-user",
        priority="medium",
    )
    await db.flush()
    q2 = await create_clarification_question(
        db,
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Different text — should be ignored",
        context_json={},
        requested_by="other-user",
        priority="critical",
    )
    assert q1.id == q2.id
    assert q2.question_text == "Should we prioritize correctness or speed?"


@pytest.mark.asyncio
async def test_answer_clarification_question(db, auth_headers):
    question = await create_clarification_question(
        db,
        session_id=str(uuid.uuid4()),
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Should we prioritize correctness or speed?",
        context_json={},
        requested_by="test-user",
        priority="medium",
    )
    await db.flush()

    answered = await answer_clarification_question(
        db,
        question_id=question.id,
        answer_text="Correctness, always.",
        answered_by="test-user",
    )
    assert answered.status == "answered"
    assert answered.answer_text == "Correctness, always."
    assert answered.answered_by == "test-user"
    assert answered.answered_at is not None


@pytest.mark.asyncio
async def test_answer_clarification_already_answered_raises(db, auth_headers):
    question = await create_clarification_question(
        db,
        session_id=str(uuid.uuid4()),
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Question?",
        context_json={},
        requested_by="test-user",
    )
    await db.flush()
    await answer_clarification_question(db, question_id=question.id, answer_text="Answer 1", answered_by="user1")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await answer_clarification_question(db, question_id=question.id, answer_text="Answer 2", answered_by="user2")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_skip_clarification_question(db, auth_headers):
    question = await create_clarification_question(
        db,
        session_id=str(uuid.uuid4()),
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Question?",
        context_json={},
        requested_by="test-user",
    )
    await db.flush()

    skipped = await skip_clarification_question(
        db,
        question_id=question.id,
        skipped_by="test-user",
        reason="Not needed for now",
    )
    assert skipped.status == "skipped"
    assert skipped.answer_text == "Not needed for now"


@pytest.mark.asyncio
async def test_cancel_clarification_question_only_by_requester(db, auth_headers):
    question = await create_clarification_question(
        db,
        session_id=str(uuid.uuid4()),
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Question?",
        context_json={},
        requested_by="requester-id",
    )
    await db.flush()

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await cancel_clarification_question(db, question_id=question.id, cancelled_by="other-user")
    assert exc_info.value.status_code == 403

    cancelled = await cancel_clarification_question(db, question_id=question.id, cancelled_by="requester-id")
    assert cancelled.status == "cancelled"
