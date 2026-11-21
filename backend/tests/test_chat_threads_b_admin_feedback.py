"""Admin chat feedback round-trips and the admin chat bootstrap paginates messages and loads older pages."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Message, MessageFeedback, Project, Session, User
from app.time_utils import utc_now
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_admin_chat_feedback_roundtrip(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"feedback-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Feedback thread"},
    )
    db.add(session)
    await db.flush()
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Helpful answer",
        model="stepfun/step-3.5-flash:free",
    )
    db.add(message)
    await db.commit()

    feedback_resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/messages/{message.id}/feedback",
        json={"rating": "bad", "disliked": "Zu generisch", "aspects": {"completeness": "disliked"}},
    )
    assert feedback_resp.status_code == 200

    await db.refresh(message)
    feedback = (
        await db.execute(
            select(MessageFeedback).where(
                MessageFeedback.message_id == message.id,
                MessageFeedback.user_id == admin_user.id,
            )
        )
    ).scalar_one_or_none()
    assert feedback is not None
    assert feedback.rating == -1
    assert feedback.comment is None

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
    assert bootstrap_resp.status_code == 200
    selected_messages = bootstrap_resp.json()["selectedMessages"]
    shown = selected_messages[0]["feedback"]
    assert (shown["rating"], shown["liked"], shown["disliked"]) == ("bad", None, "Zu generisch")
    assert shown["aspects"] == {"completeness": "disliked"}


@pytest.mark.asyncio
async def test_admin_chat_bootstrap_paginates_messages_and_loads_older_pages(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Paginated thread", "thinking_level": "light", "runtime_target_id": ""},
    )
    db.add(session)
    await db.flush()

    base_time = utc_now() - timedelta(minutes=5)
    for index in range(85):
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role="assistant" if index % 2 else "user",
                content=f"message-{index}",
                created_at=base_time + timedelta(seconds=index),
            )
        )
    await db.commit()

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
    assert bootstrap_resp.status_code == 200
    bootstrap_payload = bootstrap_resp.json()
    assert len(bootstrap_payload["selectedMessages"]) == 80
    assert bootstrap_payload["selectedMessagesHasMore"] is True
    assert bootstrap_payload["selectedMessages"][0]["content"] == "message-5"
    assert bootstrap_payload["selectedMessages"][-1]["content"] == "message-84"

    oldest_loaded_message_id = bootstrap_payload["selectedMessages"][0]["id"]
    older_resp = await client.get(
        f"/admin/chat/api/sessions/{session.id}/messages?before_message_id={oldest_loaded_message_id}"
    )
    assert older_resp.status_code == 200
    older_payload = older_resp.json()
    assert older_payload["hasMore"] is False
    assert [message["content"] for message in older_payload["messages"]] == [
        "message-0",
        "message-1",
        "message-2",
        "message-3",
        "message-4",
    ]
