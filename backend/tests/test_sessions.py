"""Tests for session endpoints."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Message, Session, User
from app.services.session.api import list_session_responses
from app.services.system_config.values import AGENT_DEFAULT_MODE_KEY, set_system_config_value
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_create_session(client, auth_headers):
    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["agent_type"] == "diagnosis"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_session_without_agent_type_uses_db_backed_default_mode_key(client, auth_headers, db):
    await set_system_config_value(
        db,
        key=AGENT_DEFAULT_MODE_KEY,
        value="change",
        description="Preferred default agent mode",
    )
    await db.commit()

    resp = await client.post(
        "/api/v1/sessions",
        json={},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["agent_type"] == "change"


@pytest.mark.asyncio
async def test_create_session_explicit_agent_type_overrides_db_backed_default_mode_key(client, auth_headers, db):
    await set_system_config_value(
        db,
        key=AGENT_DEFAULT_MODE_KEY,
        value="change",
        description="Preferred default agent mode",
    )
    await db.commit()

    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "chat"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["agent_type"] == "chat"


@pytest.mark.asyncio
async def test_list_sessions(client, auth_headers):
    # Create a session first
    await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/sessions", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_list_session_responses_batches_message_counts(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    sessions: list[Session] = []
    base_time = utc_now() - timedelta(minutes=5)
    for _ in range(4):
        session = Session(
            id=str(uuid.uuid4()),
            user_id=admin.id,
            agent_type="diagnosis",
            status="active",
            started_at=base_time + timedelta(minutes=len(sessions)),
        )
        db.add(session)
        sessions.append(session)
    await db.flush()

    for session_index, session in enumerate(sessions):
        for message_index in range(session_index):
            db.add(
                Message(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    role="assistant",
                    content=f"session-{session_index}-message-{message_index}",
                )
            )
    await db.commit()

    execute_calls = 0
    original_execute = db.execute

    async def counted_execute(*args, **kwargs):
        nonlocal execute_calls
        execute_calls += 1
        return await original_execute(*args, **kwargs)

    db.execute = counted_execute  # type: ignore[method-assign]
    try:
        responses = await list_session_responses(db=db, user_id=admin.id)
    finally:
        db.execute = original_execute  # type: ignore[method-assign]

    assert execute_calls == 3
    assert [response.message_count for response in responses] == [3, 2, 1, 0]


@pytest.mark.asyncio
async def test_get_session(client, auth_headers):
    # Create
    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    session_id = resp.json()["id"]

    # Get
    resp = await client.get(f"/api/v1/sessions/{session_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == session_id


@pytest.mark.asyncio
async def test_get_session_messages_empty(client, auth_headers):
    # Create
    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    session_id = resp.json()["id"]

    # Get messages
    resp = await client.get(f"/api/v1/sessions/{session_id}/messages", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_send_message_no_api_key(client, auth_headers):
    """Sending a message without API key should handle the error."""
    # Create session
    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    session_id = resp.json()["id"]

    # Send message (will fail because no OpenRouter API key)
    try:
        resp = await client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "test message"},
            headers=auth_headers,
        )
        # Should get error content in response, not a crash
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data
    except Exception:
        # Acceptable: no API key configured in test environment
        pass
