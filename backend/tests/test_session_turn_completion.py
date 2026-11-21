import uuid

import pytest

from app.models import Message, Session, ToolCall
from app.services.session.run_state import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    get_session_run_completion_reason,
    get_session_run_status,
)
from app.services.session.turn_completion import finalize_chat_turn_after_agent_stream
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_finalize_chat_turn_after_agent_stream_marks_completed_and_builds_follow_up(db):
    session_id = str(uuid.uuid4())
    user_message_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        user_id="user-1",
        agent_type="documentation",
        status="running",
        metadata_={
            "current_turn_user_message_id": user_message_id,
            "current_turn_started_at": utc_now().isoformat(),
        },
    )
    assistant_message = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content="Workflow complete.",
    )
    db.add_all(
        [
            session,
            Message(id=user_message_id, session_id=session_id, role="user", content="Create the report."),
            assistant_message,
        ]
    )
    await db.flush()

    result = await finalize_chat_turn_after_agent_stream(db, session_id=session_id)
    await db.flush()

    assert result.run_status == RUN_STATUS_COMPLETED
    assert result.run_completion_reason == "completed"
    assert result.latest_assistant_message_id == assistant_message.id
    assert result.completion_follow_up == {
        "session_id": session_id,
        "project_id": None,
        "agent_type": "documentation",
        "latest_assistant_message_id": assistant_message.id,
        "latest_assistant_content": "Workflow complete.",
        "completion_reason": "completed",
    }
    assert session.status == "active"
    assert get_session_run_status(session) == RUN_STATUS_COMPLETED
    assert "current_turn_user_message_id" not in (session.metadata_ or {})


@pytest.mark.asyncio
async def test_finalize_chat_turn_after_agent_stream_marks_validation_failure(db):
    session_id = str(uuid.uuid4())
    user_message_id = str(uuid.uuid4())
    turn_started_at = utc_now()
    session = Session(
        id=session_id,
        user_id="user-1",
        agent_type="coding",
        status="running",
        metadata_={
            "current_turn_user_message_id": user_message_id,
            "current_turn_started_at": turn_started_at.isoformat(),
        },
    )
    assistant_message = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content="Migration completed.",
    )
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session_id,
        message_id=assistant_message.id,
        tool_name="run_test_suite",
        status="success",
        result={"all_green": False, "exit_code": 1, "command": ["pytest"]},
        created_at=turn_started_at,
    )
    db.add_all(
        [
            session,
            Message(id=user_message_id, session_id=session_id, role="user", content="Migrate the repo."),
            assistant_message,
            tool_call,
        ]
    )
    await db.flush()

    result = await finalize_chat_turn_after_agent_stream(db, session_id=session_id)
    await db.flush()

    assert result.run_status == RUN_STATUS_FAILED
    assert result.run_completion_reason == "validation_failed"
    assert result.completion_follow_up is None
    assert get_session_run_status(session) == RUN_STATUS_FAILED
    assert get_session_run_completion_reason(session) == "validation_failed"
    assert (session.metadata_ or {}).get("completion_blocker", {}).get("tool_call_id") == tool_call.id


@pytest.mark.asyncio
async def test_finalize_chat_turn_after_agent_stream_preserves_pending_approval_state(db):
    session_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        user_id="user-1",
        agent_type="coding",
        status="pending_approval",
        metadata_={"current_turn_user_message_id": str(uuid.uuid4())},
    )
    db.add(session)
    await db.flush()

    result = await finalize_chat_turn_after_agent_stream(db, session_id=session_id)
    await db.flush()

    assert result.session_status == "pending_approval"
    assert result.run_status == RUN_STATUS_AWAITING_APPROVAL
    assert result.run_completion_reason == "approval_required"
    assert result.completion_follow_up is None
    assert get_session_run_status(session) == RUN_STATUS_AWAITING_APPROVAL
    assert "current_turn_user_message_id" not in (session.metadata_ or {})


@pytest.mark.asyncio
async def test_finalize_chat_turn_after_agent_stream_is_noop_for_missing_session(db):
    session_id = str(uuid.uuid4())

    result = await finalize_chat_turn_after_agent_stream(db, session_id=session_id)

    assert result.session_status == "missing"
    assert result.run_status == RUN_STATUS_COMPLETED
    assert await db.get(Session, session_id) is None
