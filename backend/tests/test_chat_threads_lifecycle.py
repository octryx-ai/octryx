"""Stopping, archiving (with child threads) and renaming chat threads, and the archived list on the settings page."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Message, Project, Session, User
from tests.conftest import ADMIN_PASSWORD


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
