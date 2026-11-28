"""Presence per person and device (``services.agent_gateway.presence_devices``)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AgentPresence, AuditLog, Project, User
from app.services.agent_gateway.presence_devices import (
    REMOVE_AUDIT_ACTION,
    _key,
    collapse_entries,
    entry_id,
    expire_presence,
    remove_presence_entry,
    retained,
)
from app.time_utils import utc_now
from tests.factories import make_project


async def _project(db) -> Project:
    return await make_project(db, name=f"presence-{uuid.uuid4().hex[:8]}")


async def _user(db) -> User:
    user = User(username=f"p-{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@example.test",
                password_hash="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


def _row(user: User, project: Project, *, device: str, stopped_days: float | None = None,
         seen_days: float = 0) -> AgentPresence:
    now = utc_now()
    return AgentPresence(id=str(uuid.uuid4()), session_key=str(uuid.uuid4()), user_id=user.id,
                         project_id=project.id, profile="seat", client="claude-code",
                         device_key=_key(user.id, f"device:{device}"),
                         registered_at=now - timedelta(days=seen_days), last_seen_at=now - timedelta(days=seen_days),
                         stopped_at=None if stopped_days is None else now - timedelta(days=stopped_days))


def test_sessions_of_one_device_collapse_and_show_the_running_one():
    user, project = User(id="u1"), Project(id="p1")
    stopped = _row(user, project, device="mac", stopped_days=0.1)
    running = _row(user, project, device="mac", seen_days=0.2)
    other = _row(user, project, device="laptop", stopped_days=1)
    entries = collapse_entries([(stopped,), (running,), (other,)])
    assert [(result[0] is running, count) for result, count in entries[:1]] == [(True, 1)]
    assert len(entries) == 2
    assert entry_id(running) != entry_id(other)


@pytest.mark.asyncio
async def test_rows_past_seven_days_are_not_listed_and_the_sweep_deletes_them(db):
    project, user = await _project(db), await _user(db)
    fresh = _row(user, project, device="mac", stopped_days=6)
    old_stopped = _row(user, project, device="mac", stopped_days=8)
    old_unseen = _row(user, project, device="laptop", seen_days=9)
    db.add_all([fresh, old_stopped, old_unseen])
    await db.flush()
    listed = (await db.execute(select(AgentPresence.id).where(AgentPresence.project_id == project.id,
                                                              retained(utc_now())))).scalars().all()
    assert listed == [fresh.id]
    assert await expire_presence(db) == 2
    left = (await db.execute(select(AgentPresence.id).where(AgentPresence.project_id == project.id))).scalars().all()
    assert left == [fresh.id]


@pytest.mark.asyncio
async def test_a_person_removes_only_their_own_entry_and_an_admin_any_audited(db):
    project, owner, other = await _project(db), await _user(db), await _user(db)
    mine = [_row(owner, project, device="mac"), _row(owner, project, device="mac", stopped_days=1)]
    theirs = _row(other, project, device="mac")
    db.add_all([*mine, theirs])
    await db.flush()

    assert await remove_presence_entry(db, project_id=project.id, entry=entry_id(theirs), actor_id=owner.id,
                                       may_remove_others=False) == 0
    assert await remove_presence_entry(db, project_id=project.id, entry=entry_id(mine[0]), actor_id=owner.id,
                                       may_remove_others=False) == 2
    assert await remove_presence_entry(db, project_id=project.id, entry=entry_id(theirs), actor_id=owner.id,
                                       may_remove_others=True) == 1
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == REMOVE_AUDIT_ACTION,
                                                      AuditLog.user_id == owner.id))).scalars().all()
    assert sorted(a.details["by_other"] for a in audits) == [False, True]
    assert (await db.execute(select(AgentPresence).where(AgentPresence.project_id == project.id))).first() is None


@pytest.mark.asyncio
async def test_the_list_names_a_registered_device_and_leaves_plain_clients_without_one(db):
    from app.models.security.device import UserDevice
    from app.services.agent_gateway.presence import list_presence

    project, user = await _project(db), await _user(db)
    device = UserDevice(owner_user_id=user.id, name="Mac Alice", name_key="mac alice", os="macos",
                        public_key="test-public-key", folders=[], profiles=[])
    db.add(device)
    await db.flush()
    on_device = _row(user, project, device="mac")
    on_device.device_id = device.id
    plain = _row(user, project, device="laptop")
    db.add_all([on_device, plain])
    await db.flush()

    items = {item["id"]: item for item in (await list_presence(db, project_id=project.id,
                                                                include_allowance=False))["items"]}
    assert items[entry_id(on_device)]["device"] == {"id": device.id, "name": "Mac Alice"}
    assert items[entry_id(plain)]["device"] is None
