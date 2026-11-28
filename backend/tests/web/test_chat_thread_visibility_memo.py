"""The bootstrap resolves the user's sidebar visibility once, not once per group, count and list."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Session
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
async def test_the_bootstrap_resolves_visibility_once(client, auth_headers, db, monkeypatch, auth_user):
    for project in (await db.execute(select(Project).limit(2))).scalars():
        db.add(Session(id=str(uuid.uuid4()), user_id=auth_user.id, project_id=project.id, agent_type="diagnosis",
                       status="active", metadata_={"title": f"In {project.name}"}))
    db.add(Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
                   metadata_={"title": "No project"}))
    await db.commit()
    calls = _counting_admin_check(monkeypatch)

    response = await client.get("/chat/api/bootstrap", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()["activeThreadGroups"]) >= 2
    assert calls == [auth_user.id]


@pytest.mark.asyncio
async def test_outside_a_bootstrap_every_call_resolves_afresh(db, monkeypatch, auth_user):
    calls = _counting_admin_check(monkeypatch)

    first = await chat_thread_visibility.visible_thread_project_ids(db, user=auth_user)
    second = await chat_thread_visibility.visible_thread_project_ids(db, user=auth_user)
    with chat_thread_visibility.thread_visibility_memo():
        third = await chat_thread_visibility.visible_thread_project_ids(db, user=auth_user)
        third[0].add("mutating a copy never changes the memo")
        fourth = await chat_thread_visibility.visible_thread_project_ids(db, user=auth_user)

    assert first == second == fourth
    assert len(calls) == 3
