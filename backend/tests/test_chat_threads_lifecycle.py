"""Stopping, archiving (with child threads) and renaming chat threads, and the archived list on the settings page."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.agent.engine import (
    AgentEvent,
)
from app.models import Message, Project, Session, User
from app.services.session import turn_runner
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_thread_can_be_stopped(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    started = asyncio.Event()
    cancelled = asyncio.Event()

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
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        yield AgentEvent(role="assistant", content="Should not complete")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={"prompt": "Long running task"},
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()
    session_id = payload["selectedSession"]["id"]
    assert payload["selectedSessionIsRunning"] is True

    await asyncio.wait_for(started.wait(), timeout=1)

    stop_resp = await client.post(f"/admin/chat/api/sessions/{session_id}/stop", json={})
    assert stop_resp.status_code == 200
    stop_payload = stop_resp.json()
    assert stop_payload["selectedSessionIsRunning"] is False
    assert stop_payload["selectedSession"]["status"] == "stopped"
    assert stop_payload["selectedSession"]["runStatus"] == "stopped"
    assert stop_payload["selectedSession"]["runCompletionReason"] == "user_cancelled"
    assert stop_payload["selectedMessages"][-1]["content"] == "Generation stopped by user."
    await asyncio.wait_for(cancelled.wait(), timeout=1)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_settings_page_lists_archived_threads(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    archived_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=None,
        agent_type="diagnosis",
        status="archived",
        metadata_={"title": "Archived verification thread", "runtime_label": "Automatic fallback chain"},
    )
    db.add(archived_session)
    await db.flush()
    db.add(
        Message(
            id=str(uuid.uuid4()),
            session_id=archived_session.id,
            role="assistant",
            content="Archived summary",
        )
    )
    await db.commit()

    page_resp = await client.get("/admin/settings")
    assert page_resp.status_code == 200
    assert "Archived Threads" in page_resp.text
    assert "Archived verification thread" in page_resp.text
    assert "Restore" in page_resp.text


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_archiving_parent_thread_archives_children(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        metadata_={"title": "Parent thread"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
        parent_session_id=parent_session.id,
        metadata_={"title": "Child thread"},
    )
    db.add(parent_session)
    db.add(child_session)
    await db.commit()

    archive_resp = await client.post(f"/admin/chat/api/sessions/{parent_session.id}/archive")
    assert archive_resp.status_code == 200

    await db.refresh(parent_session)
    await db.refresh(child_session)
    assert parent_session.status == "archived"
    assert child_session.status == "archived"

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={parent_session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    assert payload["selectedSessionIsArchived"] is True
    assert payload["selectedSession"]["status"] == "archived"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_thread_can_be_renamed(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Old title"},
    )
    db.add(session)
    await db.commit()

    rename_resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/rename",
        json={"title": "Updated thread name"},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["selectedSession"]["title"] == "Updated thread name"

    await db.refresh(session)
    assert (session.metadata_ or {}).get("title") == "Updated thread name"
