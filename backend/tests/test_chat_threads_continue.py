"""Continuing a failed thread in its session, the task agent fallback, and the seeded Jira worker path."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.agent.engine import (
    AgentEvent,
)
from app.models import AgentDefinition, Message, Project, Session, Task, User
from app.services.session import turn_runner
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_failed_thread_can_continue_in_same_session(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=None,
        agent_type="change",
        status="error",
        metadata_={"title": "Failed thread", "thinking_level": "deep"},
    )
    db.add(session)
    await db.commit()

    observed = {}

    async def fake_run_agent(
        *,
        session_id,
        user_message,
        user_id,
        project_id,
        agent_type,
        db,
        runtime_target_id=None,
        thinking_level=None,
        agent_definition=None,
        run_origin=None,
    ):
        observed["session_id"] = session_id
        observed["user_message"] = user_message
        observed["thinking_level"] = thinking_level
        await asyncio.sleep(0.05)
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="Continued work",
                model="stepfun/step-3.5-flash:free",
            )
        )
        await db.commit()
        yield AgentEvent(role="assistant", content="Continued work")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    continue_resp = await client.post(f"/admin/chat/api/sessions/{session.id}/continue", json={})
    assert continue_resp.status_code == 200
    payload = continue_resp.json()
    assert payload["selectedSession"]["id"] == session.id
    assert payload["selectedSessionIsRunning"] is True

    final_payload = payload
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert observed["session_id"] == session.id
    assert "Continue from the previous failure" in observed["user_message"]
    assert observed["thinking_level"] == "deep"
    assert final_payload["selectedMessages"][-1]["content"] == "Continued work"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_continue_uses_task_agent_when_session_metadata_has_no_agent_id(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin_user.id,
        project_id=project.id,
        name="Ticket Agent",
        description="Worker",
        goal="Process ticket",
        agent_type="change",
        thinking_level="deep",
        branch_prefix="octryx",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Ticket action",
        description="Runs the ticket agent",
        task_type="agent_run",
        agent_type="change",
        schedule=None,
        config={"agent_definition_id": agent.id},
        is_active=True,
        owner_id=admin_user.id,
    )
    db.add(task)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="error",
        metadata_={"title": "Failed task thread", "task_id": task.id},
    )
    db.add(session)
    await db.commit()

    observed = {}

    async def fake_run_agent(
        *,
        session_id,
        user_message,
        user_id,
        project_id,
        agent_type,
        db,
        runtime_target_id=None,
        thinking_level=None,
        agent_definition=None,
        run_origin=None,
    ):
        observed["session_id"] = session_id
        observed["agent_definition"] = agent_definition
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="Continued with task agent",
                model="stepfun/step-3.5-flash:free",
            )
        )
        await db.commit()
        yield AgentEvent(role="assistant", content="Continued with task agent")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    continue_resp = await client.post(f"/admin/chat/api/sessions/{session.id}/continue", json={})
    assert continue_resp.status_code == 200
    assert continue_resp.json()["selectedSession"]["id"] == session.id
    for _ in range(20):
        if "session_id" in observed:
            break
        await asyncio.sleep(0.05)

    assert observed["session_id"] == session.id
    assert observed["agent_definition"]["name"] == "Ticket Agent"
