"""Chat sidebar bulk actions."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, Message, Session, User
from app.services.session import thread_bulk
from app.services.session.turn_tasks import CHAT_RUN_TASKS

BULK_URL = "/chat/api/threads/bulk"


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


def _thread(user_id: str, title: str, *, status: str = "active", started_at: datetime | None = None) -> Session:
    return Session(
        id=str(uuid.uuid4()),
        user_id=user_id,
        agent_type="diagnosis",
        status=status,
        metadata_={"title": title},
        started_at=started_at or datetime.now(UTC).replace(tzinfo=None),
    )


async def _seed(db, user_id: str, titles: list[str], **kwargs) -> list[Session]:
    sessions = [_thread(user_id, title, **kwargs) for title in titles]
    db.add_all(sessions)
    await db.commit()
    return sessions


async def _statuses(db, sessions: list[Session]) -> list[str]:
    for session in sessions:
        await db.refresh(session)
    return [session.status for session in sessions]


async def _member_headers(client, auth_headers, username: str) -> dict:
    register = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "testpass123",
              "display_name": username},
        headers=auth_headers,
    )
    assert register.status_code == 200
    login = await client.post("/api/v1/auth/login", data={"username": username, "password": "testpass123"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_archiving_a_whole_group_scope_archives_unloaded_threads_in_one_request(client, auth_headers, db, auth_user):
    threads = await _seed(db, auth_user.id, [f"Group thread {index:02d}" for index in range(67)])

    response = await client.post(
        BULK_URL,
        json={"action": "archive", "scopes": [{"project_id": "", "query": "", "as_of": None, "except_ids": []}]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["affected"] == 67
    assert set(payload["affected_ids"]) == {thread.id for thread in threads}
    assert set(await _statuses(db, threads)) == {"archived"}
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "chat.threads.bulk_archive"))
    ).scalars().all()
    assert len(audit) == 1
    assert audit[0].details["counts"] == {"affected": 67, "skipped": 0}


@pytest.mark.asyncio
async def test_a_search_scope_never_archives_a_non_matching_thread(client, auth_headers, db, auth_user):
    matching = await _seed(db, auth_user.id, ["Budget review", "Q4 budget plan"])
    by_message = _thread(auth_user.id, "")
    by_message.metadata_ = {}
    db.add(by_message)
    db.add(Message(id=str(uuid.uuid4()), session_id=by_message.id, role="user", content="Draft the BUDGET memo"))
    other = await _seed(db, auth_user.id, ["Hiring pipeline", "Budge_t typo", "100% coverage"])

    count = await client.get("/chat/api/thread-groups/count?project_id=&q=budget", headers=auth_headers)
    assert count.status_code == 200
    assert count.json()["count"] == 3

    response = await client.post(
        BULK_URL,
        json={"action": "archive", "scopes": [{"project_id": "", "query": "budget", "except_ids": [matching[1].id]}]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert set(response.json()["affected_ids"]) == {matching[0].id, by_message.id}
    assert await _statuses(db, other) == ["active", "active", "active"]
    assert await _statuses(db, [matching[1]]) == ["active"]
    # LIKE wildcards in the query are literal.
    literal = await client.get("/chat/api/thread-groups/count?project_id=&q=100%25", headers=auth_headers)
    assert literal.json()["count"] == 1


@pytest.mark.asyncio
async def test_a_scope_excludes_threads_started_after_as_of(client, auth_headers, db, auth_user):
    as_of = datetime.now(UTC).replace(tzinfo=None)
    older = await _seed(db, auth_user.id, ["Older"], started_at=as_of - timedelta(minutes=5))
    newer = await _seed(db, auth_user.id, ["Newer"], started_at=as_of + timedelta(minutes=5))

    response = await client.post(
        BULK_URL,
        json={"action": "archive", "scopes": [{"project_id": "", "as_of": as_of.isoformat() + "Z"}]},
        headers=auth_headers,
    )

    assert response.json()["affected_ids"] == [older[0].id]
    assert await _statuses(db, newer) == ["active"]


@pytest.mark.asyncio
async def test_running_and_failing_threads_are_skipped_and_reported_the_rest_is_processed(
    client, auth_headers, db, monkeypatch, auth_user
):
    threads = await _seed(db, auth_user.id, ["One", "Two", "Three", "Four"])
    threads[1].status = "running"
    await db.commit()
    running_task = asyncio.create_task(asyncio.Event().wait())
    CHAT_RUN_TASKS[threads[1].id] = running_task
    original = thread_bulk.archive_session_tree

    async def flaky_archive(db, *, session_id, user_id):
        if session_id == threads[2].id:
            raise RuntimeError("boom")
        await original(db, session_id=session_id, user_id=user_id)

    monkeypatch.setattr(thread_bulk, "archive_session_tree", flaky_archive)
    try:
        response = await client.post(
            BULK_URL, json={"action": "archive", "ids": [thread.id for thread in threads]}, headers=auth_headers
        )
    finally:
        CHAT_RUN_TASKS.pop(threads[1].id, None)
        running_task.cancel()

    payload = response.json()
    assert set(payload["affected_ids"]) == {threads[0].id, threads[3].id}
    assert {(item["id"], item["reason"]) for item in payload["skipped"]} == {
        (threads[1].id, "running"),
        (threads[2].id, "failed"),
    }
    assert await _statuses(db, threads) == ["archived", "running", "active", "archived"]


@pytest.mark.asyncio
async def test_dry_run_reports_the_breakdown_without_changing_anything(client, auth_headers, db, auth_user):
    threads = await _seed(db, auth_user.id, ["Parent", "Solo"])
    child = _thread(auth_user.id, "Child")
    child.parent_session_id = threads[0].id
    db.add(child)
    await db.commit()

    response = await client.post(
        BULK_URL,
        json={"action": "archive", "ids": [thread.id for thread in threads], "dry_run": True},
        headers=auth_headers,
    )

    payload = response.json()
    assert payload["counts"]["affected"] == 2
    assert payload["counts"]["sub_chats"] == 1
    assert payload["by_project"] == [{"project_id": "", "project_name": "No project", "count": 2}]
    assert await _statuses(db, [*threads, child]) == ["active", "active", "active"]


@pytest.mark.asyncio
async def test_restore_undoes_exactly_the_archived_ids(client, auth_headers, db, auth_user):
    threads = await _seed(db, auth_user.id, ["Keep archived", "Undo me"])
    threads[0].status = "archived"
    await db.commit()

    archived = await client.post(BULK_URL, json={"action": "archive", "ids": [threads[1].id]}, headers=auth_headers)
    restored = await client.post(
        BULK_URL, json={"action": "restore", "ids": archived.json()["affected_ids"]}, headers=auth_headers
    )

    assert restored.json()["affected_ids"] == [threads[1].id]
    assert await _statuses(db, threads) == ["archived", "active"]


@pytest.mark.asyncio
async def test_a_scope_or_id_never_touches_another_users_threads(client, auth_headers, db):
    member_headers = await _member_headers(client, auth_headers, "bulk-scope-member")
    member = (await db.execute(select(User).where(User.username == "bulk-scope-member"))).scalar_one()
    admin = await _admin(db)
    admin_threads = await _seed(db, admin.id, ["Admin thread"])
    member_threads = await _seed(db, member.id, ["Member thread"])

    response = await client.post(
        BULK_URL,
        json={"action": "archive", "ids": [admin_threads[0].id], "scopes": [{"project_id": ""}]},
        headers=member_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert admin_threads[0].id not in payload["affected_ids"]
    assert {"id": admin_threads[0].id, "reason": "not_found"} in payload["skipped"]
    assert await _statuses(db, admin_threads) == ["active"]
    # The member sees no "No project" group, so the empty-project scope reaches nothing of theirs either.
    assert await _statuses(db, member_threads) == ["active"]


@pytest.mark.asyncio
async def test_members_get_403_for_bulk_delete_and_admins_delete_the_tree(client, auth_headers, db):
    member_headers = await _member_headers(client, auth_headers, "bulk-delete-member")
    admin = await _admin(db)
    threads = await _seed(db, admin.id, ["Delete me"])

    refused = await client.post(BULK_URL, json={"action": "delete", "ids": [threads[0].id]}, headers=member_headers)
    assert refused.status_code == 403

    deleted = await client.post(BULK_URL, json={"action": "delete", "ids": [threads[0].id]}, headers=auth_headers)
    assert deleted.json()["affected_ids"] == [threads[0].id]
    assert (await db.execute(select(Session).where(Session.id == threads[0].id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_single_archive_answers_ok_without_a_chat_state(client, auth_headers, db, auth_user):
    threads = await _seed(db, auth_user.id, ["Single"])

    response = await client.post(f"/chat/api/sessions/{threads[0].id}/archive", json={}, headers=auth_headers)

    assert response.json() == {"ok": True, "id": threads[0].id}
    assert await _statuses(db, threads) == ["archived"]
