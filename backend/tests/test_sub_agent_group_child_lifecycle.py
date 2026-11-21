"""Child terminal states resume the parent once, and child sessions fail on weak research evidence or terminalize when cancelled."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Session, SubAgentGroup, User
from app.services.session.run_state import get_session_run_completion_reason, get_session_run_status
from app.services.sub_agent_group import (
    _run_child_session,
    create_sub_agent_group,
    mark_sub_agent_group_child_terminal,
)


@pytest.mark.asyncio
async def test_mark_sub_agent_group_child_terminal_resumes_parent_once(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="awaiting_subagents",
        metadata_={
            "title": "Parent orchestration",
            "current_sub_agent_group_id": "",
            "thinking_level": "light",
        },
    )
    child_a = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        metadata_={"title": "Inspect alpha"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    child_b = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        metadata_={"title": "Inspect beta"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    db.add_all([parent_session, child_a, child_b])
    await db.flush()
    group = await create_sub_agent_group(
        db,
        parent_session_id=parent_session.id,
        child_session_ids=[child_a.id, child_b.id],
    )
    metadata = dict(parent_session.metadata_ or {})
    metadata["current_sub_agent_group_id"] = group.id
    parent_session.metadata_ = metadata
    db.add(parent_session)
    await db.commit()

    import app.services.session.turn_start as turn_start_module

    resumed = []
    group_id = group.id

    async def fake_start_turn(request, *, session_factory=None):
        resumed.append(
            {
                "session_id": request.session_id,
                "prompt": request.prompt,
                "thinking_level": request.thinking_level,
            }
        )
        async with session_factory() as resume_db:
            session = await resume_db.get(Session, request.session_id)
            if session is not None:
                session.status = "running"
                resume_db.add(session)
                await resume_db.commit()
        return session

    monkeypatch.setattr(turn_start_module, "start_turn", fake_start_turn)
    parent_session_id = parent_session.id

    await mark_sub_agent_group_child_terminal(
        session_factory=async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False),
        group_id=group_id,
        child_session_id=child_a.id,
        child_status="completed",
    )
    await mark_sub_agent_group_child_terminal(
        session_factory=async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False),
        group_id=group_id,
        child_session_id=child_b.id,
        child_status="failed",
        error="synthetic failure",
    )

    db.expire_all()
    refreshed_group = await db.get(SubAgentGroup, group_id)
    assert refreshed_group is not None
    assert refreshed_group.completed_count == 1
    assert refreshed_group.failed_count == 1
    assert refreshed_group.status == "resumed"
    assert refreshed_group.resumed_at is not None
    assert len(resumed) == 1
    assert resumed[0]["session_id"] == parent_session_id


@pytest.mark.asyncio
async def test_run_child_session_marks_a_child_without_tool_evidence_as_failed(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="awaiting_subagents",
        metadata_={"title": "Parent document orchestration"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        agent_type="documentation",
        metadata_={"title": "Research child"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    db.add_all([parent_session, child_session])
    await db.flush()
    parent_session_id = parent_session.id
    child_session_id = child_session.id
    group = await create_sub_agent_group(
        db,
        parent_session_id=parent_session_id,
        child_session_ids=[child_session_id],
    )
    group_id = group.id
    await db.commit()

    async def fake_run_agent(**kwargs):
        yield SimpleNamespace(
            role="assistant",
            content="Empty result. Trying a more specific search with common ticketing platforms and integration patterns.",
            model="claude-haiku-4.5",
        )

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)

    await _run_child_session(
        session_factory=async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False),
        group_id=group_id,
        parent_session_id=parent_session_id,
        session_id=child_session_id,
        task="Research ticketing API integration evidence",
        user_id=admin.id,
        project_id=None,
        agent_type="documentation",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        sub_agent_depth=1,
    )

    db.expire_all()
    refreshed_child = await db.get(Session, child_session_id)
    refreshed_group = await db.get(SubAgentGroup, group_id)

    assert refreshed_child is not None
    assert refreshed_child.status == "error"
    assert get_session_run_status(refreshed_child) == "failed"
    assert get_session_run_completion_reason(refreshed_child) == "sub_agent_rejected"
    assert "no_successful_tool_calls" in (refreshed_child.metadata_ or {}).get("sub_agent_rejection_reasons", [])
    assert refreshed_group is not None
    assert refreshed_group.failed_count == 1


@pytest.mark.asyncio
async def test_run_child_session_terminalizes_cancelled_child(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="awaiting_subagents",
        metadata_={"title": "Parent orchestration"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        agent_type="coding",
        metadata_={"title": "Inspect source compatibility"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    db.add_all([parent_session, child_session])
    await db.flush()
    group = await create_sub_agent_group(
        db,
        parent_session_id=parent_session.id,
        child_session_ids=[child_session.id],
    )
    parent_session_id = parent_session.id
    child_session_id = child_session.id
    group_id = group.id
    await db.commit()

    async def fake_run_agent(**kwargs):
        await asyncio.Event().wait()
        if False:
            yield SimpleNamespace(role="assistant", content="", model="test")

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)

    task = asyncio.create_task(
        _run_child_session(
            session_factory=async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False),
            group_id=group_id,
            parent_session_id=parent_session_id,
            session_id=child_session_id,
            task="Inspect source compatibility. Do not edit files.",
            user_id=admin.id,
            project_id=None,
            agent_type="coding",
            runtime_target_id=None,
            thinking_level="light",
            agent_definition=None,
            sub_agent_depth=1,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel("validation timeout")
    with pytest.raises(asyncio.CancelledError):
        await task

    db.expire_all()
    refreshed_child = await db.get(Session, child_session_id)
    refreshed_group = await db.get(SubAgentGroup, group_id)

    assert refreshed_child is not None
    assert refreshed_child.status == "stopped"
    assert get_session_run_status(refreshed_child) == "failed"
    assert get_session_run_completion_reason(refreshed_child) == "sub_agent_cancelled"
    assert (refreshed_child.metadata_ or {}).get("cancel_reason") == "validation timeout"
    assert refreshed_group is not None
    assert refreshed_group.failed_count == 1
    assert refreshed_group.status == "completed"
