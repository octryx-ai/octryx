"""Focused tests for chat session thread lifecycle mutations."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Session, User
from tests.conftest import ADMIN_PASSWORD


async def _login_admin(client) -> None:
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303


@pytest.mark.asyncio
async def test_chat_thread_restore_updates_tree_status(client, db):
    await _login_admin(client)

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="archived",
        metadata_={"title": "Parent thread"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=project.id,
        agent_type="change",
        status="archived",
        parent_session_id=parent_session.id,
        metadata_={"title": "Child thread"},
    )
    db.add(parent_session)
    db.add(child_session)
    await db.commit()

    restore_resp = await client.post(f"/admin/chat/api/sessions/{parent_session.id}/restore")
    assert restore_resp.status_code == 200

    await db.refresh(parent_session)
    await db.refresh(child_session)
    assert parent_session.status == "active"
    assert child_session.status == "active"

    bootstrap_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={parent_session.id}")
    assert bootstrap_resp.status_code == 200
    payload = bootstrap_resp.json()
    assert payload["selectedSessionIsArchived"] is False
    assert payload["selectedSession"]["status"] == "active"


@pytest.mark.asyncio
async def test_chat_thread_pin_toggle_updates_selected_session_contract(client, db):
    await _login_admin(client)

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Pinned thread"},
    )
    db.add(session)
    await db.commit()

    pin_resp = await client.post(f"/admin/chat/api/sessions/{session.id}/pin")
    assert pin_resp.status_code == 200
    assert pin_resp.json()["selectedSession"]["isPinned"] is True

    await db.refresh(session)
    assert (session.metadata_ or {}).get("pinned") is True

    unpin_resp = await client.post(f"/admin/chat/api/sessions/{session.id}/unpin")
    assert unpin_resp.status_code == 200
    assert unpin_resp.json()["selectedSession"]["isPinned"] is False

    await db.refresh(session)
    assert (session.metadata_ or {}).get("pinned") is False
