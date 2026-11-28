"""API tests for clarifications routes."""

import uuid

import pytest

from app.models import ClarificationQuestion, Session


@pytest.mark.asyncio
async def test_create_clarification_via_api(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    await db.flush()

    resp = await client.post(
        "/api/v1/clarifications",
        json={
            "session_id": session_id,
            "project_id": None,
            "run_id": None,
            "question_id": "scope-missing",
            "question_text": "Should we prioritize correctness or speed?",
            "context_json": {"iteration": 0},
            "priority": "high",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert data["status"] == "open"
    assert data["question_id"] == "scope-missing"
    assert data["priority"] == "high"


@pytest.mark.asyncio
async def test_list_clarifications(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    for i in range(3):
        q = ClarificationQuestion(
            id=str(uuid.uuid4()),
            session_id=session_id,
            project_id=None,
            run_id=None,
            question_id=f"q-{i}",
            question_text=f"Question {i}?",
            context_json={},
            status="open",
            priority="medium",
            requested_by=auth_user.id,
        )
        db.add(q)
    await db.flush()

    resp = await client.get("/api/v1/clarifications", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 3
    for item in data["items"]:
        assert "id" in item
        assert "status" in item


@pytest.mark.asyncio
async def test_list_clarifications_filtered_by_session(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-filter",
        question_text="Filter test?",
        context_json={},
        status="open",
        priority="medium",
        requested_by=auth_user.id,
    )
    db.add(q)
    await db.flush()

    resp = await client.get(f"/api/v1/clarifications?session_id={session_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert all(item["session_id"] == session_id for item in data["items"])


@pytest.mark.asyncio
async def test_get_clarification_by_id(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-get",
        question_text="Get test?",
        context_json={},
        status="open",
        priority="medium",
        requested_by=auth_user.id,
    )
    db.add(q)
    await db.flush()

    resp = await client.get(f"/api/v1/clarifications/{q.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == q.id


@pytest.mark.asyncio
async def test_answer_clarification(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-answer",
        question_text="Answer test?",
        context_json={},
        status="open",
        priority="medium",
        requested_by=auth_user.id,
    )
    db.add(q)
    await db.flush()

    resp = await client.post(
        f"/api/v1/clarifications/{q.id}/answer",
        json={"answer_text": "Yes, correctness."},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "answered"
    assert data["answer_text"] == "Yes, correctness."


@pytest.mark.asyncio
async def test_answer_clarification_not_open_returns_400(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-answer-twice",
        question_text="Answer test?",
        context_json={},
        status="answered",
        answer_text="Already answered",
        answered_by=auth_user.id,
        priority="medium",
        requested_by=auth_user.id,
    )
    db.add(q)
    await db.flush()

    resp = await client.post(
        f"/api/v1/clarifications/{q.id}/answer",
        json={"answer_text": "Second answer?"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_skip_clarification(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-skip",
        question_text="Skip test?",
        context_json={},
        status="open",
        priority="medium",
        requested_by=auth_user.id,
    )
    db.add(q)
    await db.flush()

    resp = await client.post(
        f"/api/v1/clarifications/{q.id}/skip",
        json={"reason": "Not needed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "skipped"


@pytest.mark.asyncio
async def test_cancel_clarification_by_non_requester_returns_403(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-cancel",
        question_text="Cancel test?",
        context_json={},
        status="open",
        priority="medium",
        requested_by="other-user-id",
    )
    db.add(q)
    await db.flush()

    resp = await client.post(f"/api/v1/clarifications/{q.id}/cancel", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_clarification_by_requester(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-cancel-ok",
        question_text="Cancel test?",
        context_json={},
        status="open",
        priority="medium",
        requested_by=auth_user.id,
    )
    db.add(q)
    await db.flush()

    resp = await client.post(f"/api/v1/clarifications/{q.id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"


@pytest.mark.asyncio
async def test_get_session_open_clarification_returns_answered(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-session-open",
        question_text="Session open test?",
        context_json={},
        status="answered",
        answer_text="The answer",
        answered_by=auth_user.id,
        priority="medium",
        requested_by=auth_user.id,
    )
    db.add(q)
    await db.flush()

    resp = await client.get(f"/api/v1/clarifications/session/{session_id}/open", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "answered"
    assert data["answer_text"] == "The answer"


@pytest.mark.asyncio
async def test_get_session_open_clarification_returns_none_when_no_active(client, db, auth_headers, auth_user):
    session_id = str(uuid.uuid4())
    db.add(Session(id=session_id, user_id=auth_user.id, project_id=None, agent_type="diagnosis", metadata_={}))
    q = ClarificationQuestion(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=None,
        run_id=None,
        question_id="test-session-open-none",
        question_text="Session open test?",
        context_json={},
        status="cancelled",
        priority="medium",
        requested_by=auth_user.id,
    )
    db.add(q)
    await db.flush()

    resp = await client.get(f"/api/v1/clarifications/session/{session_id}/open", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data is None
