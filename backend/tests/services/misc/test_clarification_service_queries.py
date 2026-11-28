"""Reading, listing, serializing and expiring clarification questions."""

import uuid

import pytest

from app.services.clarification_service import (
    answer_clarification_question,
    create_clarification_question,
    get_clarification_by_id,
    get_open_clarification_for_session,
    list_clarification_questions,
    serialize_clarification,
    skip_clarification_question,
)
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_get_clarification_by_id(db, auth_headers):
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
    found = await get_clarification_by_id(db, question_id=question.id)
    assert found.id == question.id


@pytest.mark.asyncio
async def test_get_clarification_not_found(db, auth_headers):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await get_clarification_by_id(db, question_id=str(uuid.uuid4()))
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_open_clarification_for_session_returns_answered(db, auth_headers):
    session_id = str(uuid.uuid4())
    question = await create_clarification_question(
        db,
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Question?",
        context_json={},
        requested_by="test-user",
    )
    await db.flush()
    await answer_clarification_question(db, question_id=question.id, answer_text="Answer", answered_by="user1")

    open_q = await get_open_clarification_for_session(db, session_id=session_id)
    assert open_q is not None
    assert open_q.status == "answered"


@pytest.mark.asyncio
async def test_get_open_clarification_for_session_returns_question_when_open(db, auth_headers):
    session_id = str(uuid.uuid4())
    await create_clarification_question(
        db,
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="scope-missing",
        question_text="Question?",
        context_json={},
        requested_by="test-user",
    )
    await db.flush()
    open_q = await get_open_clarification_for_session(db, session_id=session_id)
    assert open_q is not None
    assert open_q.status == "open"


@pytest.mark.asyncio
async def test_list_clarification_questions_filters_by_status_and_session(db, auth_headers):
    session_id = str(uuid.uuid4())
    for i in range(3):
        q = await create_clarification_question(
            db,
            session_id=session_id,
            project_id=None,
            run_id=None,
            question_id=f"q-{i}",
            question_text=f"Question {i}?",
            context_json={},
            requested_by="test-user",
        )
        await db.flush()
        if i == 1:
            await skip_clarification_question(db, question_id=q.id, skipped_by="test-user")

    all_qs = await list_clarification_questions(db)
    assert len(all_qs) >= 3

    skipped_qs = await list_clarification_questions(db, status="skipped")
    assert any(q.status == "skipped" for q in skipped_qs)

    session_qs = await list_clarification_questions(db, session_id=session_id)
    assert len(session_qs) == 3


@pytest.mark.asyncio
async def test_serialize_clarification(db, auth_headers):
    question = await create_clarification_question(
        db,
        session_id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        question_id="scope-missing",
        question_text="Should we prioritize correctness or speed?",
        context_json={"key": "value"},
        requested_by="test-user",
        priority="high",
    )
    await db.flush()
    data = serialize_clarification(question)
    assert data["id"] == question.id
    assert data["status"] == "open"
    assert data["question_text"] == "Should we prioritize correctness or speed?"
    assert data["context_json"] == {"key": "value"}
    assert data["answer_text"] is None
    assert data["answered_by"] is None
    assert data["created_at"] is not None


@pytest.mark.asyncio
async def test_expire_overdue_clarification_questions(db, auth_headers):
    from datetime import timedelta

    from app.services.clarification_service import expire_overdue_clarification_questions

    session_id = str(uuid.uuid4())

    expired_q = await create_clarification_question(
        db,
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="expired-q",
        question_text="This should expire",
        context_json={},
        requested_by="test-user",
        priority="medium",
        expires_at=utc_now() - timedelta(minutes=5),
    )
    await db.flush()

    future_q = await create_clarification_question(
        db,
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="future-q",
        question_text="This should stay open",
        context_json={},
        requested_by="test-user",
        priority="medium",
        expires_at=utc_now() + timedelta(hours=1),
    )
    await db.flush()

    no_expiry_q = await create_clarification_question(
        db,
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="no-expiry-q",
        question_text="This has no expiration",
        context_json={},
        requested_by="test-user",
        priority="medium",
    )
    await db.flush()

    count = await expire_overdue_clarification_questions(db)
    await db.commit()

    assert count == 1

    await db.refresh(expired_q)
    await db.refresh(future_q)
    await db.refresh(no_expiry_q)

    assert expired_q.status == "expired"
    assert expired_q.skipped_at is not None
    assert future_q.status == "open"
    assert no_expiry_q.status == "open"
