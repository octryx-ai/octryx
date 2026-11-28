"""Tests for schema boundary validation and send endpoint behavior."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Message, Session, User
from tests.conftest import ADMIN_PASSWORD
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_chat_send_requires_non_empty_prompt_at_schema_boundary(client):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    resp = await client.post("/admin/chat/api/send", json={"prompt": ""})

    assert resp.status_code == 422
    payload = resp.json()
    assert payload["error"] == "Validation failed"
    assert payload["status_code"] == 422
    assert payload["request_id"]
    assert payload["validation_errors"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_message_feedback_requires_supported_rating_at_schema_boundary(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        agent_type="chat",
        status="active",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="hello",
    )
    db.add(message)
    await db.commit()

    resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/messages/{message.id}/feedback",
        json={"rating": 0, "comment": "invalid"},
    )

    assert resp.status_code == 422
