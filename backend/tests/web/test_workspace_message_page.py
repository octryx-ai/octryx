from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import KnowledgeAnswerFeedback, Message, Project, Session, ToolCall, TurnTrace
from app.time_utils import utc_now
from app.web._helpers.workspace_message_page import load_workspace_message_page_bundle


@pytest.mark.asyncio
async def test_load_workspace_message_page_bundle_loads_related_rows_in_message_order(db, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Workspace bundle"},
    )
    db.add(session)
    await db.flush()

    base_time = utc_now() - timedelta(minutes=3)
    messages: list[Message] = []
    for index in range(3):
        message = Message(
            id=str(uuid.uuid4()),
            session_id=session.id,
            role="assistant" if index else "user",
            content=f"message-{index}",
            model="gpt-5.4-mini",
            created_at=base_time + timedelta(seconds=index),
        )
        db.add(message)
        messages.append(message)
    await db.flush()

    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=session.id,
            message_id=messages[1].id,
            tool_name="write_file",
            status="completed",
            created_at=base_time + timedelta(seconds=10),
        )
    )
    db.add(
        TurnTrace(
            id=str(uuid.uuid4()),
            session_id=session.id,
            message_id=messages[1].id,
            provider="openai",
            model="gpt-5.4-mini",
            created_at=base_time + timedelta(seconds=11),
        )
    )
    project = Project(id=str(uuid.uuid4()), name=f"bundle-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        KnowledgeAnswerFeedback(
            project_id=project.id,
            user_id=auth_user.id,
            session_id=session.id,
            message_id=messages[1].id,
            rating="good",
            liked="Solid",
        )
    )
    await db.commit()

    bundle = await load_workspace_message_page_bundle(
        db,
        session=session,
        user=auth_user,
        limit=2,
    )

    assert bundle.has_more is True
    assert [message.content for message in bundle.messages] == ["message-1", "message-2"]
    assert [tool_call.message_id for tool_call in bundle.tool_calls] == [messages[1].id]
    assert [row[0] for row in bundle.turn_trace_rows] == [messages[1].id]
    assert [(feedback["message_id"], feedback["liked"]) for feedback in bundle.feedbacks] == [
        (messages[1].id, "Solid")
    ]


@pytest.mark.asyncio
async def test_load_workspace_message_page_bundle_returns_empty_page_for_unknown_boundary(db, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Workspace bundle boundary"},
    )
    db.add(session)
    await db.commit()

    bundle = await load_workspace_message_page_bundle(
        db,
        session=session,
        user=auth_user,
        limit=10,
        before_message_id=str(uuid.uuid4()),
    )

    assert bundle.messages == []
    assert bundle.tool_calls == []
    assert bundle.turn_trace_rows == []
    assert bundle.feedbacks == []
    assert bundle.has_more is False
