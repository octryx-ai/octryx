"""A new chat never starts in an archived Workspace.

After a fresh login the chat opens the latest thread, which may live in an archived Workspace; "New chat" must not
pass that Workspace on and create the new chat there although another Workspace was chosen. A new
chat starts in the requested Workspace only while it is active, else in the Instance default (when the
person is in it), else in the person's only active Workspace, else in none. An existing thread keeps its own.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

import app.services.session.turn_runner as turn_runner
from app.models import Project, User
from app.models import Session as ChatSession
from app.models.security.user import UserProject
from app.services.project.default_workspace import set_default_workspace
from app.services.project.new_chat_workspace import fallback_new_chat_workspace, new_chat_workspace
from app.services.session.turn_tasks import CHAT_RUN_TASKS
from tests.conftest import ADMIN_PASSWORD


async def _workspace(db, name: str, *, active: bool = True) -> Project:
    project = Project(name=f"{name}-{uuid.uuid4().hex[:8]}", config={}, is_active=active)
    db.add(project)
    await db.flush()
    return project


async def _member(db, user: User, *projects: Project) -> None:
    for project in projects:
        exists = (await db.execute(select(UserProject).where(
            UserProject.user_id == user.id, UserProject.project_id == project.id))).scalar_one_or_none()
        if exists is None:
            db.add(UserProject(user_id=user.id, project_id=project.id, role="member"))
    await db.flush()


async def _user(db) -> User:
    handle = f"chatter{uuid.uuid4().hex[:8]}"
    user = User(username=handle, email=f"{handle}@example.test", password_hash="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


# --- the rule ---------------------------------------------------------------------------------------------------


async def test_an_active_or_empty_request_is_kept(db):
    user = await _user(db)
    active = await _workspace(db, "active")
    await _member(db, user, active)

    assert await new_chat_workspace(db, user=user, project_id=active.id) == active.id
    assert await new_chat_workspace(db, user=user, project_id="") == ""


async def test_an_archived_request_falls_back_to_the_default_the_person_is_in(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    user = await _user(db)
    archived, chosen, other = (await _workspace(db, "archived", active=False), await _workspace(db, "chosen"),
                               await _workspace(db, "other"))
    await _member(db, user, archived, chosen, other)
    await set_default_workspace(db, project_id=chosen.id, actor_id=admin.id)

    assert await new_chat_workspace(db, user=user, project_id=archived.id) == chosen.id
    unknown = str(uuid.uuid4())
    assert await new_chat_workspace(db, user=user, project_id=unknown) == unknown  # left to the access check


async def test_without_a_usable_default_the_only_active_workspace_or_none(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    user = await _user(db)
    archived, only = await _workspace(db, "archived", active=False), await _workspace(db, "only")
    elsewhere = await _workspace(db, "elsewhere")
    await _member(db, user, archived, only)
    await set_default_workspace(db, project_id=elsewhere.id, actor_id=admin.id)  # not one of theirs

    assert await new_chat_workspace(db, user=user, project_id=archived.id) == only.id

    second = await _workspace(db, "second")
    await _member(db, user, second)
    assert await fallback_new_chat_workspace(db, user=user) == ""  # two to choose from, no default of theirs


# --- bootstrap and send -----------------------------------------------------------------------------------------


@pytest.fixture
def recorded_run(monkeypatch):
    state: dict[str, Any] = {"calls": []}

    async def recording_run_agent(**kwargs):
        state["calls"].append(kwargs)
        return
        yield  # an async generator, like run_agent

    monkeypatch.setattr(turn_runner, "run_agent", recording_run_agent)
    return state


async def _admin_with_archived_latest_thread(client, db) -> tuple[str, str, str]:
    """``(acme-orders id, archived Workspace id, latest thread id)``; Acme Orders is the Instance default."""
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    acme_orders = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    archived = await _workspace(db, "[acceptance] S5 alerts", active=False)
    await _member(db, admin, acme_orders, archived)
    await set_default_workspace(db, project_id=acme_orders.id, actor_id=admin.id)
    latest = ChatSession(id=str(uuid.uuid4()), user_id=admin.id, project_id=archived.id, status="active",
                         agent_type="chat")
    db.add(latest)
    ids = (acme_orders.id, archived.id, latest.id)
    await db.commit()
    return ids


@pytest.mark.asyncio
async def test_new_chat_after_login_does_not_start_in_the_archived_workspace(client, db):
    acme_orders_id, archived_id, latest_id = await _admin_with_archived_latest_thread(client, db)

    opened = (await client.get(f"/chat/api/bootstrap?session_id={latest_id}")).json()
    assert opened["selectedSession"]["id"] == latest_id
    assert opened["selectedProjectId"] == archived_id  # the existing thread keeps its Workspace

    # "New chat" passes the chat's Workspace on (frontend useThreadSidebarActions.handleNewThread).
    fresh = (await client.get(f"/chat/api/bootstrap?new=1&project_id={archived_id}")).json()
    assert fresh["selectedSession"] is None
    # The person's private Workspace comes before the Instance default.
    [private] = [item["id"] for item in fresh["projects"] if item.get("private")]
    assert fresh["selectedProjectId"] == private and private != acme_orders_id

    other_id = (await _workspace(db, "still-active")).id
    await db.commit()
    kept = (await client.get(f"/chat/api/bootstrap?new=1&project_id={other_id}")).json()
    assert kept["selectedProjectId"] == other_id


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_send_naming_an_archived_workspace_starts_the_chat_in_the_default(client, db, recorded_run):
    acme_orders_id, archived_id, _latest_id = await _admin_with_archived_latest_thread(client, db)

    response = await client.post("/chat/api/send", json={
        "prompt": "Hello", "project_id": archived_id, "workflow_key": "none"})

    assert response.status_code == 200, response.text
    session_id = response.json()["selectedSession"]["id"]
    task = CHAT_RUN_TASKS.get(session_id)
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=30)
    db.expire_all()
    created = await db.get(ChatSession, session_id)
    assert created.project_id == acme_orders_id


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_reply_in_a_thread_of_an_archived_workspace_stays_there(client, db, recorded_run):
    _acme_orders_id, archived_id, latest_id = await _admin_with_archived_latest_thread(client, db)

    response = await client.post("/chat/api/send", json={
        "prompt": "Follow-up", "session_id": latest_id, "project_id": archived_id, "workflow_key": "none"})

    assert response.status_code == 200, response.text
    task = CHAT_RUN_TASKS.get(latest_id)
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=30)
    db.expire_all()
    assert (await db.get(ChatSession, latest_id)).project_id == archived_id
