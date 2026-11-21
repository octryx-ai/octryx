from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Message, Session, ToolCall, User
from app.services.chat_turn_background import drain_chat_turn_background_tasks
from app.services.session import turn_follow_up, turn_runner, turn_settlement
from app.services.session.run_state import RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, get_session_run_status
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_complete_chat_turn_commits_completion_before_follow_up_hooks(db, monkeypatch):
    admin = (
        await db.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    session_id = str(uuid.uuid4())
    user_message_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        user_id=admin.id,
        agent_type="documentation",
        status="running",
        metadata_={"current_turn_user_message_id": user_message_id},
    )
    db.add(session)
    db.add(
        Message(
            id=user_message_id,
            session_id=session_id,
            role="user",
            content="Create the report.",
        )
    )
    await db.commit()
    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    follow_up_started = asyncio.Event()
    release_follow_up = asyncio.Event()

    async def fake_run_agent(**kwargs):
        run_db = kwargs["db"]
        assistant_message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Workflow complete.",
        )
        run_db.add(assistant_message)
        await run_db.flush()
        yield SimpleNamespace(role="assistant", content="Workflow complete.", model="fake-model")

    async def blocking_follow_up(_db, *, event_type: str, **kwargs):
        assert event_type == "session.completed"
        follow_up_started.set()
        await release_follow_up.wait()

    async def no_op_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)
    monkeypatch.setattr(turn_follow_up, "emit_outbound_webhook_event", blocking_follow_up)
    monkeypatch.setattr(turn_settlement.session_stream_manager, "publish", no_op_publish)

    task = asyncio.create_task(
        turn_runner.run_chat_turn(
            session_factory=session_factory,
            session_id=session_id,
            user_id=admin.id,
            prompt="Create the report.",
            project_id=None,
            agent_type="documentation",
            runtime_target_id=None,
            thinking_level="light",
            agent_definition=None,
            request_id=None,
        )
    )

    await asyncio.wait_for(task, timeout=2)

    async with session_factory() as verify_db:
        committed_session = await verify_db.get(Session, session_id)
        assert committed_session is not None
        assert committed_session.status == "active"
        assert get_session_run_status(committed_session) == RUN_STATUS_COMPLETED
        assert "current_turn_user_message_id" not in (committed_session.metadata_ or {})

    await asyncio.wait_for(follow_up_started.wait(), timeout=2)
    release_follow_up.set()
    await asyncio.wait_for(drain_chat_turn_background_tasks(session_id), timeout=2)


@pytest.mark.asyncio
async def test_complete_chat_turn_marks_failed_when_latest_validation_is_red(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session_id = str(uuid.uuid4())
    user_message_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        user_id=admin.id,
        agent_type="coding",
        status="running",
        metadata_={"current_turn_user_message_id": user_message_id},
    )
    db.add(session)
    db.add(Message(id=user_message_id, session_id=session_id, role="user", content="Migrate the repo."))
    await db.commit()
    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    async def fake_run_agent(**kwargs):
        run_db = kwargs["db"]
        assistant_message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Migration completed.",
        )
        run_db.add(assistant_message)
        run_db.add(
            ToolCall(
                id=str(uuid.uuid4()),
                session_id=session_id,
                message_id=assistant_message.id,
                tool_name="run_test_suite",
                status="success",
                result={"all_green": False, "exit_code": 1, "command": ["mvn", "-q", "test"]},
            )
        )
        await run_db.flush()
        yield SimpleNamespace(role="assistant", content="Migration completed.", model="fake-model")

    async def no_op_follow_up(*args, **kwargs):
        return None

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("completion follow-up must not run after red validation")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)
    monkeypatch.setattr(turn_follow_up, "emit_outbound_webhook_event", fail_if_called)
    monkeypatch.setattr(turn_settlement.session_stream_manager, "publish", no_op_follow_up)

    await turn_runner.run_chat_turn(
        session_factory=session_factory,
        session_id=session_id,
        user_id=admin.id,
        prompt="Migrate the repo.",
        project_id=None,
        agent_type="coding",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        request_id=None,
    )

    async with session_factory() as verify_db:
        committed_session = await verify_db.get(Session, session_id)
        assert committed_session is not None
        assert committed_session.status == "active"
        assert get_session_run_status(committed_session) == RUN_STATUS_FAILED
        assert (committed_session.metadata_ or {}).get("run_completion_reason") == "validation_failed"
        assert (committed_session.metadata_ or {}).get("completion_blocker", {}).get("exit_code") == 1


@pytest.mark.asyncio
async def test_complete_chat_turn_ignores_red_validation_from_previous_turn(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session_id = str(uuid.uuid4())
    user_message_id = str(uuid.uuid4())
    current_turn_started_at = utc_now()
    old_message_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        user_id=admin.id,
        agent_type="knowledge",
        status="running",
        metadata_={
            "current_turn_user_message_id": user_message_id,
            "current_turn_started_at": current_turn_started_at.isoformat(),
            "completion_blocker": {"reason": "latest_test_validation_failed", "exit_code": 1},
        },
    )
    db.add(session)
    db.add(Message(id=user_message_id, session_id=session_id, role="user", content="Summarize Report Builder."))
    db.add(Message(id=old_message_id, session_id=session_id, role="assistant", content="Old failed coding turn."))
    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=session_id,
            message_id=old_message_id,
            tool_name="run_test_suite",
            status="success",
            result={"all_green": False, "exit_code": 1, "command": ["pytest"]},
            created_at=current_turn_started_at - timedelta(seconds=10),
        )
    )
    await db.commit()
    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    async def fake_run_agent(**kwargs):
        run_db = kwargs["db"]
        assistant_message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Report Builder builds weekly order reports.",
        )
        run_db.add(assistant_message)
        await run_db.flush()
        yield SimpleNamespace(
            role="assistant", content="Report Builder builds weekly order reports.", model="fake-model"
        )

    async def no_op_follow_up(*args, **kwargs):
        return None

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)
    monkeypatch.setattr(turn_follow_up, "emit_outbound_webhook_event", no_op_follow_up)
    monkeypatch.setattr(turn_settlement.session_stream_manager, "publish", no_op_follow_up)

    await turn_runner.run_chat_turn(
        session_factory=session_factory,
        session_id=session_id,
        user_id=admin.id,
        prompt="Summarize Report Builder.",
        project_id=None,
        agent_type="knowledge",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        request_id=None,
    )

    async with session_factory() as verify_db:
        committed_session = await verify_db.get(Session, session_id)
        assert committed_session is not None
        assert committed_session.status == "active"
        assert get_session_run_status(committed_session) == RUN_STATUS_COMPLETED
        assert "completion_blocker" not in (committed_session.metadata_ or {})
