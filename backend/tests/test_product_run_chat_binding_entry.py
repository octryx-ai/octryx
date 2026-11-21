"""Both chat entry paths bind the chat origin, and a bound turn survives user erasure and names its stored run in the turn summary."""

# ruff: noqa: F811  (the shared ``world`` fixture is imported, then requested by name)
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import DeletionRequest, Project, TurnTrace, User
from app.models import Session as ChatSession
from app.services.chat_turn_background import drain_chat_turn_background_tasks
from app.services.privacy.service import process_pending_deletion_requests
from app.services.session import turn_runner, turn_settlement
from app.services.session.message_dispatch import send_session_message
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from tests.product_run_chat_binding_support import FINAL_RESPONSE, TOOL_RESPONSE, _attempt, _drain, _session, _turn
from tests.product_run_chat_support import world  # noqa: F401 - fixture
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


async def _raise_after_stream(*_args, **_kwargs):
    # Stop the UI turn task right after the stream; its completion hooks are not under test.
    raise RuntimeError("stream observed")


@pytest.mark.asyncio
async def test_both_chat_entry_paths_bind_the_chat_origin(db, monkeypatch) -> None:
    session = await _session(db)
    seen: list[Any] = []

    async def record_run_agent(**kwargs):
        seen.append(kwargs.get("run_origin"))
        if False:
            yield None

    async def no_publish(*_args, **_kwargs):
        return None

    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    # /api/v1: the canonical message route.
    await send_session_message(
        db,
        session_id=session.id,
        content="ping",
        user_id=session.user_id,
        project_id=session.project_id,
        agent_type="chat",
        run_agent_func=record_run_agent,
        session_factory=session_factory,
    )
    await drain_chat_turn_background_tasks(session.id)
    # /chat/api: the UI turn task.
    monkeypatch.setattr(turn_runner, "run_agent", record_run_agent)
    monkeypatch.setattr(turn_settlement, "finalize_chat_turn_after_agent_stream", _raise_after_stream)
    monkeypatch.setattr(turn_settlement.session_stream_manager, "publish", no_publish)
    await turn_runner.run_chat_turn(
        session_factory=session_factory,
        session_id=session.id,
        user_id=session.user_id,
        prompt="ping",
        project_id=session.project_id,
        agent_type="chat",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        request_id=None,
    )
    assert seen == ["chat_turn", "chat_turn"]


@pytest.mark.asyncio
async def test_user_erasure_still_succeeds_after_a_bound_turn(db, world) -> None:
    world["script"] = [FINAL_RESPONSE]
    target_user = User(
        id=str(uuid.uuid4()),
        username=f"run-erasure-{uuid.uuid4().hex[:8]}",
        email=f"run-erasure-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        display_name="Run Erasure",
    )
    db.add(target_user)
    project = Project(name=f"run-erasure-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = ChatSession(
        id=str(uuid.uuid4()), user_id=target_user.id, project_id=project.id, agent_type="chat", metadata_=dict(UNDECLARED_READ_ONLY_RUN)
    )
    db.add(session)
    await db.commit()
    await _drain(_turn(db, session))
    assert (await _attempt(db, session.id)).state == "finished_unverified"
    db.add(DeletionRequest(requested_by=target_user.id, target_user_id=target_user.id, reason="run binding test"))
    await db.commit()

    async def no_export(*_args, **_kwargs):
        return None

    assert await process_pending_deletion_requests(db, export_user_data_func=no_export) == 1
    assert (await db.execute(select(ChatSession).where(ChatSession.id == session.id))).first() is None


@pytest.mark.asyncio
async def test_the_summary_of_a_bound_turn_names_its_stored_run(db, world) -> None:
    """The binding writes the stamp, the trace reads it: every trace of a finished turn resolves to the stored run."""
    world.update(script=[TOOL_RESPONSE, FINAL_RESPONSE])
    session = await _session(db)

    await _drain(_turn(db, session))

    attempt = await _attempt(db, session.id)
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    for trace in traces:
        summary = await load_user_turn_execution_summary(db, user_id=session.user_id, trace_id=trace.id)
        assert summary["run_identity"] == {
            "kind": "product_run",
            "product_run_id": attempt.run_id,
            "run_state": "finished_unverified",
            "attempt": {
                "id": attempt.id,
                "number": attempt.attempt_number,
                "state": "finished_unverified",
                "end_reason": "runtime_finished",
            },
        }
        # A chat turn never claims completion.
        assert "verification" not in summary
        assert summary["state"] != "completed"
