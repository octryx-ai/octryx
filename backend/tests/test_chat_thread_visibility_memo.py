"""The bootstrap resolves the user's sidebar visibility once, not once per group, count and list."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Session, User
from app.web._helpers import chat_thread_visibility


def _counting_admin_check(monkeypatch) -> list[str]:
    calls: list[str] = []
    original = chat_thread_visibility.is_global_admin

    async def counting(db, user_id):
        calls.append(user_id)
        return await original(db, user_id)

    monkeypatch.setattr(chat_thread_visibility, "is_global_admin", counting)
    return calls


@pytest.mark.asyncio
async def test_the_bootstrap_resolves_visibility_once(client, auth_headers, db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    for project in (await db.execute(select(Project).limit(2))).scalars():
        db.add(Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="diagnosis",
                       status="active", metadata_={"title": f"In {project.name}"}))
    db.add(Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active",
                   metadata_={"title": "No project"}))
    await db.commit()
    calls = _counting_admin_check(monkeypatch)

    response = await client.get("/chat/api/bootstrap", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()["activeThreadGroups"]) >= 2
    assert calls == [admin.id]


@pytest.mark.asyncio
async def test_outside_a_bootstrap_every_call_resolves_afresh(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    calls = _counting_admin_check(monkeypatch)

    first = await chat_thread_visibility.visible_thread_project_ids(db, user=admin)
    second = await chat_thread_visibility.visible_thread_project_ids(db, user=admin)
    with chat_thread_visibility.thread_visibility_memo():
        third = await chat_thread_visibility.visible_thread_project_ids(db, user=admin)
        third[0].add("mutating a copy never changes the memo")
        fourth = await chat_thread_visibility.visible_thread_project_ids(db, user=admin)

    assert first == second == fourth
    assert len(calls) == 3
