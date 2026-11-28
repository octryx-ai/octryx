from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import DeletionRequest, Message, Session, ToolCall, TurnTrace, UsageEvent, User
from app.services.privacy.service import process_pending_deletion_requests


@pytest.mark.asyncio
async def test_user_deletion_removes_session_sensitive_records(db):
    target_user = User(
        id=str(uuid.uuid4()),
        username=f"privacy-target-{uuid.uuid4().hex[:8]}",
        email=f"privacy-target-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        display_name="Privacy Target",
    )
    db.add(target_user)
    await db.flush()

    session = Session(user_id=target_user.id, agent_type="diagnosis", status="active")
    db.add(session)
    await db.flush()

    message = Message(
        session_id=session.id,
        role="user",
        content="Sensitive enterprise prompt",
        tool_calls=[{"name": "secret_lookup"}],
        tool_results=[{"value": "sensitive"}],
    )
    db.add(message)
    await db.flush()

    db.add_all(
        [
            ToolCall(
                session_id=session.id,
                message_id=message.id,
                tool_name="read_file",
                parameters={"path": "secret.txt"},
                result={"content": "secret"},
            ),
            TurnTrace(
                session_id=session.id,
                message_id=message.id,
                provider="test",
                model="test-model",
                input_messages_json=[{"content": "secret"}],
                raw_output={"content": "secret"},
            ),
            UsageEvent(
                session_id=session.id,
                user_id=target_user.id,
                provider="test",
                model="test-model",
                tokens_in=1,
                tokens_out=1,
            ),
            DeletionRequest(
                requested_by=target_user.id,
                target_user_id=target_user.id,
                reason="privacy contract test",
            ),
        ]
    )
    await db.commit()

    async def fake_export_user_data(*_args, **_kwargs):
        return None

    processed = await process_pending_deletion_requests(db, export_user_data_func=fake_export_user_data)

    assert processed == 1
    assert (await db.execute(select(Session).where(Session.id == session.id))).scalar_one_or_none() is None
    assert (await db.execute(select(Message).where(Message.id == message.id))).scalar_one_or_none() is None
    assert (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all() == []
    assert (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all() == []
    assert (await db.execute(select(UsageEvent).where(UsageEvent.user_id == target_user.id))).scalars().all() == []

    updated_user = (await db.execute(select(User).where(User.id == target_user.id))).scalar_one()
    assert updated_user.is_active is False
    assert updated_user.username.startswith("deleted-user-")
    assert updated_user.email.startswith("deleted+")
