"""Chat sidebar rows: last activity and device badge."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import DeviceJob, Message, Session, User, UserDevice

PAGE_URL = "/admin/chat/api/thread-groups?project_id=&offset=0&limit=100"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _device(owner_id: str, name: str) -> UserDevice:
    return UserDevice(
        id=f"dev-{uuid.uuid4().hex[:12]}", owner_user_id=owner_id, name=name, name_key=name.lower(), os="macos",
        public_key="pk",
    )


@pytest.mark.asyncio
async def test_a_thread_continued_today_moves_to_the_top(client, auth_headers, db, auth_user):
    old_but_active = Session(
        id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
        metadata_={"title": "Started last month"}, started_at=_now() - timedelta(days=30), last_activity_at=_now(),
    )
    recent_but_idle = Session(
        id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
        metadata_={"title": "Started yesterday"}, started_at=_now() - timedelta(days=1),
        last_activity_at=_now() - timedelta(days=1),
    )
    db.add_all([recent_but_idle, old_but_active])
    await db.commit()

    rows = (await client.get(PAGE_URL, headers=auth_headers)).json()["sessions"]

    ids = [row["id"] for row in rows]
    assert ids.index(old_but_active.id) < ids.index(recent_but_idle.id)
    row = next(row for row in rows if row["id"] == old_but_active.id)
    assert row["lastActivityAt"].startswith(old_but_active.last_activity_at.isoformat()[:16])


@pytest.mark.asyncio
async def test_the_device_badge_names_only_the_owners_own_device(client, auth_headers, db, auth_user):
    other = User(id=str(uuid.uuid4()), username=f"other-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@x.io",
                 password_hash="x")
    db.add(other)
    own_device = _device(auth_user.id, "Studio laptop")
    foreign_device = _device(other.id, "Someone else's box")
    db.add_all([own_device, foreign_device])
    own = Session(
        id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active", origin="device_chat",
        metadata_={"title": "On my laptop", "execution_target": {"kind": "device", "device_id": own_device.id}},
    )
    foreign = Session(
        id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active", origin="device_chat",
        metadata_={"title": "Foreign id", "execution_target": {"kind": "device", "device_id": foreign_device.id}},
    )
    server = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
                     metadata_={"title": "On the server"})
    db.add_all([own, foreign, server])
    await db.commit()

    rows = {row["id"]: row for row in (await client.get(PAGE_URL, headers=auth_headers)).json()["sessions"]}

    assert rows[own.id]["executionTarget"] == {"kind": "device", "deviceName": "Studio laptop",
                                               "engine": "claude_code", "profile": None, "model": None}
    assert rows[foreign.id]["executionTarget"] is None
    assert rows[server.id]["executionTarget"] is None


@pytest.mark.asyncio
async def test_a_device_thread_names_engine_profile_and_model_of_its_newest_job(client, auth_headers, db, auth_user):
    # The phone's run line: the newest job's engine, the thread's profile, the model the device reported
    # (else the one the chat asked for).
    device = _device(auth_user.id, "MacBook")
    db.add(device)
    target = {"kind": "device", "device_id": device.id, "profile": "seat", "model": "gpt-5-codex"}
    reported = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
                       origin="device_chat", metadata_={"title": "Codex on the Mac", "execution_target": target})
    asked = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
                    origin="device_chat", metadata_={"title": "Not reported yet",
                                                     "execution_target": {**target, "profile": "governed"}})
    db.add_all([reported, asked])
    await db.flush()
    older = _now() - timedelta(hours=1)
    db.add_all([
        DeviceJob(device_id=device.id, owner_user_id=auth_user.id, session_id=reported.id, folder="/src", profile="seat",
                  engine=None, model="claude-opus-5-5", created_at=older),
        DeviceJob(device_id=device.id, owner_user_id=auth_user.id, session_id=reported.id, folder="/src", profile="seat",
                  engine="codex", model="gpt-5.1-codex", created_at=_now()),
    ])
    await db.commit()

    rows = {row["id"]: row for row in (await client.get(PAGE_URL, headers=auth_headers)).json()["sessions"]}

    assert rows[reported.id]["executionTarget"] == {"kind": "device", "deviceName": "MacBook", "engine": "codex",
                                                    "profile": "seat", "model": "gpt-5.1-codex"}
    assert rows[asked.id]["executionTarget"] == {"kind": "device", "deviceName": "MacBook", "engine": "claude_code",
                                                 "profile": "governed", "model": "gpt-5-codex"}


@pytest.mark.asyncio
async def test_search_finds_an_unloaded_thread_by_title_or_first_message(client, auth_headers, db, auth_user):
    filler = [
        Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
                metadata_={"title": f"Filler {index:02d}"}, last_activity_at=_now() - timedelta(minutes=index))
        for index in range(25)
    ]
    old_match = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
                        metadata_={"title": "Quarterly budget review"}, last_activity_at=_now() - timedelta(days=90))
    by_message = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active",
                         metadata_={"title": "Untitled"}, last_activity_at=_now() - timedelta(days=91))
    db.add_all([*filler, old_match, by_message])
    db.add(Message(id=str(uuid.uuid4()), session_id=by_message.id, role="user", content="Draft the BUDGET memo"))
    await db.commit()

    search = await client.get("/chat/api/thread-groups/search?q=budget", headers=auth_headers)
    page = await client.get("/chat/api/thread-groups?project_id=&q=budget&offset=1&limit=1", headers=auth_headers)
    empty = await client.get("/chat/api/thread-groups/search?q=%20", headers=auth_headers)

    groups = search.json()["groups"]
    no_project = next(group for group in groups if group["projectId"] == "")
    assert no_project["totalThreadCount"] == 2
    assert [row["id"] for row in no_project["sessions"]] == [old_match.id, by_message.id]
    assert [row["id"] for row in page.json()["sessions"]] == [by_message.id]
    assert empty.json() == {"query": "", "groups": []}


@pytest.mark.asyncio
async def test_archived_chats_are_listed_and_counted_for_restore(client, auth_headers, db, auth_user):
    archived = [
        Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="archived",
                metadata_={"title": f"Archived {index}"}, last_activity_at=_now() - timedelta(hours=index))
        for index in range(3)
    ]
    machine = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="archived",
                      origin="webhook", metadata_={"title": "Webhook run"})
    db.add_all([*archived, machine])
    await db.commit()

    page = (await client.get("/chat/api/threads/archived?offset=0&limit=2", headers=auth_headers)).json()
    bootstrap = (await client.get("/admin/chat/api/bootstrap?new=true", headers=auth_headers)).json()

    assert page["total"] == 3
    assert [row["id"] for row in page["threads"]] == [archived[0].id, archived[1].id]
    assert page["hasMore"] is True
    assert bootstrap["archivedThreadCount"] == 3
