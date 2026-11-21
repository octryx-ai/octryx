"""Launching a group respects its concurrency limit, and waiting terminalizes children still waiting for the semaphore."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Session, SubAgentGroup, User
from app.services.session.run_state import get_session_run_completion_reason
from app.services.sub_agent_group import (
    create_sub_agent_group,
    launch_sub_agent_group,
    wait_for_sub_agent_group_tasks_for_parent,
)


@pytest.mark.asyncio
async def test_launch_sub_agent_group_respects_max_concurrent_children(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="awaiting_subagents",
        metadata_={"title": "Parent concurrency orchestration"},
    )
    child_sessions = [
        Session(
            id=str(uuid.uuid4()),
            user_id=admin.id,
            status="active",
            agent_type="documentation",
            metadata_={"title": f"Child {index}"},
            parent_session_id=parent_session.id,
            sub_agent_depth=1,
        )
        for index in range(3)
    ]
    db.add(parent_session)
    db.add_all(child_sessions)
    await db.flush()
    group = await create_sub_agent_group(
        db,
        parent_session_id=parent_session.id,
        child_session_ids=[child.id for child in child_sessions],
    )
    await db.commit()

    in_flight = 0
    max_seen = 0
    observed: list[str] = []

    async def fake_run_child_session(**kwargs):
        nonlocal in_flight, max_seen
        in_flight += 1
        max_seen = max(max_seen, in_flight)
        observed.append(kwargs["session_id"])
        await asyncio.sleep(0.05)
        in_flight -= 1

    async def fake_watch_timeout(**kwargs):
        return None

    monkeypatch.setattr("app.services.sub_agent_group.service._run_child_session", fake_run_child_session)
    monkeypatch.setattr("app.services.sub_agent_group.service._watch_sub_agent_group_timeout", fake_watch_timeout)

    await launch_sub_agent_group(
        session_factory=async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False),
        group_id=group.id,
        parent_session_id=parent_session.id,
        user_id=admin.id,
        project_id=None,
        agent_type="documentation",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        sub_agent_depth=1,
        child_runs=[
            {"session_id": child.id, "task": f"Research slice {index}"}
            for index, child in enumerate(child_sessions, start=1)
        ],
        max_concurrent_children=2,
    )
    await asyncio.sleep(0.2)

    assert max_seen == 2
    assert sorted(observed) == sorted(child.id for child in child_sessions)


@pytest.mark.asyncio
async def test_wait_for_sub_agent_group_tasks_terminalizes_children_waiting_for_semaphore(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="awaiting_subagents",
        metadata_={"title": "Parent serialized orchestration"},
    )
    child_sessions = [
        Session(
            id=str(uuid.uuid4()),
            user_id=admin.id,
            status="active",
            agent_type="coding",
            metadata_={"title": f"Child {index}"},
            parent_session_id=parent_session.id,
            sub_agent_depth=1,
        )
        for index in range(2)
    ]
    db.add(parent_session)
    db.add_all(child_sessions)
    await db.flush()
    group = await create_sub_agent_group(
        db,
        parent_session_id=parent_session.id,
        child_session_ids=[child.id for child in child_sessions],
    )
    parent_session_id = parent_session.id
    group_id = group.id
    await db.commit()

    started_child_ids: list[str] = []

    async def fake_run_child_session(**kwargs):
        started_child_ids.append(kwargs["session_id"])
        await asyncio.Event().wait()

    async def fake_watch_timeout(**kwargs):
        return None

    monkeypatch.setattr("app.services.sub_agent_group.service._run_child_session", fake_run_child_session)
    monkeypatch.setattr("app.services.sub_agent_group.service._watch_sub_agent_group_timeout", fake_watch_timeout)

    session_factory = async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False)
    await launch_sub_agent_group(
        session_factory=session_factory,
        group_id=group_id,
        parent_session_id=parent_session_id,
        user_id=admin.id,
        project_id=None,
        agent_type="coding",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        sub_agent_depth=1,
        child_runs=[
            {"session_id": child.id, "task": f"Inspect migration slice {index}"}
            for index, child in enumerate(child_sessions, start=1)
        ],
        max_concurrent_children=1,
    )
    await asyncio.sleep(0.05)

    drain = await wait_for_sub_agent_group_tasks_for_parent(
        session_factory=session_factory,
        parent_session_id=parent_session_id,
        timeout_seconds=0.1,
        cancel_pending=True,
        cancel_reason="validation timeout",
    )

    await asyncio.sleep(0.05)
    db.expire_all()
    refreshed_children = (
        await db.execute(select(Session).where(Session.parent_session_id == parent_session_id))
    ).scalars().all()
    refreshed_group = await db.get(SubAgentGroup, group_id)

    assert drain["completed"] is True
    assert drain["cancelled_task_count"] == 2
    waiting_child_ids = {child.id for child in child_sessions} - set(started_child_ids)
    assert waiting_child_ids
    waiting_children = [child for child in refreshed_children if child.id in waiting_child_ids]
    assert {child.status for child in waiting_children} == {"stopped"}
    assert all(get_session_run_completion_reason(child) == "sub_agent_cancelled" for child in waiting_children)
    assert refreshed_group is not None
    assert refreshed_group.failed_count >= 1
