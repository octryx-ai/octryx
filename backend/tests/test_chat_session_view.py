"""The selected-session view: a chat switch gets the bootstrap's selected fields without the workspace."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Approval, Message, Project, Session, ToolCall, User
from app.web._helpers._chat_selected_view_fields import SELECTED_VIEW_KEYS


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _thread(db, user: User, *, status: str = "active", parent: Session | None = None, title: str = "") -> Session:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()), user_id=user.id, project_id=project.id, agent_type="diagnosis", status=status,
        parent_session_id=parent.id if parent else None, metadata_={"title": title or "A thread"},
        started_at=_now() - timedelta(minutes=5),
    )
    db.add(session)
    await db.flush()
    return session


def _view_fields(payload: dict) -> dict:
    fields = {key: payload[key] for key in SELECTED_VIEW_KEYS}
    if fields["selectedSession"]:
        fields["selectedSession"] = {
            key: value
            for key, value in fields["selectedSession"].items()
            # A sidebar ordinal (the view loads no sidebar) and a freshly signed token.
            if key not in {"threadNumber", "streamToken"}
        }
    return fields


@pytest.mark.asyncio
async def test_the_view_returns_exactly_the_bootstraps_selected_fields(client, auth_headers, db):
    admin = await _admin(db)
    parent = await _thread(db, admin, title="Parent thread")
    child = await _thread(db, admin, parent=parent, title="Sub thread")
    await _thread(db, admin, title="Another thread in the sidebar")
    for index in range(3):
        db.add(Message(id=str(uuid.uuid4()), session_id=parent.id, role="user", content=f"question {index}"))
        db.add(Message(id=str(uuid.uuid4()), session_id=parent.id, role="assistant", content=f"answer {index}",
                       model="m-1"))
    db.add(Message(id=str(uuid.uuid4()), session_id=child.id, role="assistant", content="child", model="m-2"))
    db.add(ToolCall(session_id=parent.id, tool_name="read_file", parameters={"path": "a.txt"},
                    result={"ok": True}, status="success"))
    db.add(Approval(requested_by=admin.id, session_id=parent.id, action="tool:shell", status="pending"))
    await db.commit()

    for session in (parent, child):
        bootstrap = await client.get(f"/chat/api/bootstrap?session_id={session.id}", headers=auth_headers)
        view = await client.get(f"/chat/api/sessions/{session.id}/view", headers=auth_headers)
        assert bootstrap.status_code == 200 and view.status_code == 200
        payload = view.json()
        assert set(payload) == set(SELECTED_VIEW_KEYS)
        assert _view_fields(payload) == _view_fields(bootstrap.json())
        assert payload["selectedSession"]["id"] == session.id
        assert payload["selectedSession"]["threadNumber"] == 0
        assert payload["selectedSession"]["streamToken"]

    parent_view = (await client.get(f"/chat/api/sessions/{parent.id}/view", headers=auth_headers)).json()
    assert len(parent_view["selectedMessages"]) == 6
    assert parent_view["selectedSession"]["pendingApprovalCount"] == 1
    assert parent_view["traceEventCount"] == 1
    # The sub thread's usage is summed into the parent thread's stats, as in the bootstrap.
    assert parent_view["selectedThreadStats"]["messageCount"] == 7


@pytest.mark.asyncio
async def test_a_missing_or_foreign_thread_is_reported_never_swapped(client, auth_headers, db):
    admin = await _admin(db)
    await _thread(db, admin, title="The user's latest thread")
    other = User(id=str(uuid.uuid4()), username=f"other-{uuid.uuid4().hex[:6]}",
                 email=f"{uuid.uuid4().hex[:6]}@example.invalid", password_hash="x")
    db.add(other)
    await db.flush()
    foreign = await _thread(db, other, title="Someone else's thread")
    await db.commit()

    for session_id in (foreign.id, str(uuid.uuid4())):
        response = await client.get(f"/chat/api/sessions/{session_id}/view", headers=auth_headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["requestedSessionNotFound"] is True
        assert payload["selectedSession"] is None
        assert payload["selectedMessages"] == []
        assert payload["traceEvents"] == []
        assert payload["selectedSessionIsArchived"] is False
        assert payload["selectedSessionIsRunning"] is False


@pytest.mark.asyncio
async def test_the_view_requires_a_signed_in_user(client, db):
    admin = await _admin(db)
    session = await _thread(db, admin)
    await db.commit()

    response = await client.get(f"/chat/api/sessions/{session.id}/view")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_archived_and_running_flags_follow_the_thread(client, auth_headers, db, monkeypatch):
    from app.services.session.turn_tasks import CHAT_RUN_TASKS

    admin = await _admin(db)
    archived = await _thread(db, admin, status="archived", title="Archived")
    running = await _thread(db, admin, status="running", title="Running")
    await db.commit()
    # "running" means this process runs the turn right now (a stale running row reads "active").
    live_turn = asyncio.create_task(asyncio.sleep(60))
    monkeypatch.setitem(CHAT_RUN_TASKS, running.id, live_turn)

    archived_view = (await client.get(f"/chat/api/sessions/{archived.id}/view", headers=auth_headers)).json()
    running_view = (await client.get(f"/chat/api/sessions/{running.id}/view", headers=auth_headers)).json()

    assert archived_view["selectedSessionIsArchived"] is True
    assert archived_view["selectedSessionIsRunning"] is False
    assert running_view["selectedSessionIsRunning"] is True
    assert running_view["selectedSessionIsArchived"] is False
    live_turn.cancel()


@pytest.mark.asyncio
async def test_the_view_loads_no_sidebar_archive_or_catalog(client, auth_headers, db, monkeypatch):
    from app.web._helpers import _chat_state_builder, _routing_default_selection, chat_thread_pages, chat_thread_scope

    def _forbidden(name: str):
        async def _raise(*_args, **_kwargs):
            raise AssertionError(f"the session view must not call {name}")

        return _raise

    for module, names in (
        (chat_thread_pages, ("count_chat_thread_groups", "load_chat_thread_group_page", "load_initial_chat_thread_pages",
                             "list_visible_chat_projects")),
        (chat_thread_scope, ("count_archived_threads", "load_archived_threads")),
        (_routing_default_selection, ("_list_chat_agent_catalog",)),
        (_chat_state_builder, ("count_chat_thread_groups", "load_initial_chat_thread_pages", "count_archived_threads",
                               "list_visible_chat_projects", "_list_chat_agent_catalog")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, _forbidden(name))
    admin = await _admin(db)
    session = await _thread(db, admin)
    await db.commit()

    response = await client.get(f"/chat/api/sessions/{session.id}/view", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["selectedSession"]["id"] == session.id
    assert "activeThreadGroups" not in response.json()
