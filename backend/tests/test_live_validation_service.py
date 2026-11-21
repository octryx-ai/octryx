import uuid

import pytest
from sqlalchemy import select

from app.models import (
    Message,
    MessageFeedback,
    Project,
    Session,
    SessionToolCacheEntry,
    ThreadContext,
    ToolCall,
    TurnTrace,
    User,
)
from app.services.session.tree_cleanup import cleanup_session_descendants


async def _seed_sessions_and_messages(db, user, project):
    root_session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
        parent_session_id=root_session.id,
    )
    db.add_all([root_session, child_session])
    await db.flush()

    root_message = Message(
        id=str(uuid.uuid4()),
        session_id=root_session.id,
        role="assistant",
        content="root",
    )
    child_message = Message(
        id=str(uuid.uuid4()),
        session_id=child_session.id,
        role="assistant",
        content="child",
    )
    db.add_all([root_message, child_message])
    await db.flush()
    return root_session, child_session, root_message, child_message


def _build_owned_rows(user, root_session, root_message):
    return [
        MessageFeedback(
            id=str(uuid.uuid4()),
            message_id=root_message.id,
            user_id=user.id,
            rating=1,
        ),
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=root_session.id,
            message_id=root_message.id,
            tool_name="list_failed_pods",
            parameters={},
            result={},
        ),
        TurnTrace(
            id=str(uuid.uuid4()),
            session_id=root_session.id,
            message_id=root_message.id,
            provider="test",
            model="test-model",
            input_messages_json=[],
            context_snapshot_json={},
            tool_trace_json=[],
            raw_output={},
            usage_json={},
        ),
        ThreadContext(
            id=str(uuid.uuid4()),
            session_id=root_session.id,
            context_json={"goal": "cleanup"},
        ),
        SessionToolCacheEntry(
            id=str(uuid.uuid4()),
            session_id=root_session.id,
            tool_name="list_failed_pods",
            params_hash="abc",
            result_json={"ok": True},
            ttl_seconds=60,
        ),
    ]


async def _remaining_ids(db, column):
    return (await db.execute(select(column))).scalars().all()


@pytest.mark.asyncio
async def test_cleanup_session_descendants_deletes_owned_rows_and_nullifies_optional_refs(db):
    user = (await db.execute(select(User).limit(1))).scalar_one()
    project = (await db.execute(select(Project).limit(1))).scalar_one()

    root_session, child_session, root_message, child_message = await _seed_sessions_and_messages(db, user, project)

    db.add_all(_build_owned_rows(user, root_session, root_message))
    await db.commit()

    summary = await cleanup_session_descendants(db, root_session.id)

    remaining_sessions = await _remaining_ids(db, Session.id)
    remaining_messages = await _remaining_ids(db, Message.id)
    remaining_feedbacks = await _remaining_ids(db, MessageFeedback.id)
    remaining_tool_calls = await _remaining_ids(db, ToolCall.id)
    remaining_turn_traces = await _remaining_ids(db, TurnTrace.id)
    remaining_thread_context = await _remaining_ids(db, ThreadContext.id)
    remaining_cache = await _remaining_ids(db, SessionToolCacheEntry.id)

    assert root_session.id in summary["session_ids"]
    assert child_session.id in summary["session_ids"]
    assert root_session.id not in remaining_sessions
    assert child_session.id not in remaining_sessions
    assert root_message.id not in remaining_messages
    assert child_message.id not in remaining_messages
    assert remaining_feedbacks == []
    assert remaining_tool_calls == []
    assert remaining_turn_traces == []
    assert remaining_thread_context == []
    assert remaining_cache == []
    assert summary["deleted"]["messages.id"] == 2
    assert summary["deleted"]["sessions.id"] == 2
