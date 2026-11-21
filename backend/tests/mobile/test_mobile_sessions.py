"""Octryx Mobile: the person's open octryx-claude sessions on the phone.

- a registered session is open while its launcher sends heartbeats; without one for two minutes it leaves the list,
  and a finalized session never shows;
- the activity follows the session's own calls (a tool check: working; Claude Code asking: approval; the Stop hook:
  waiting, with the title and the last answer the client sends);
- the list is the caller's own sessions only, with the Workspace, the billing profile and the activity.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AgentPresence
from app.services.agent_gateway.session_activity import note_activity, open_sessions
from app.services.auth import create_access_token
from app.time_utils import utc_now
from tests.agent_gateway.seat_presence_support import _gateway_headers, _register, _workspace
from tests.knowledge_evidence_seed_support import seed_member


async def _open_session(client, db, username: str = "terminal-owner", profile: str = "governed"):
    workspace = await _workspace(db)
    user_id = await seed_member(db, workspace_id=workspace, role="member", username=username)
    await db.commit()
    headers = await _gateway_headers(db, user_id, workspace)
    registered = await _register(client, headers, profile=profile)
    assert registered.status_code == 200, registered.text
    return user_id, workspace, headers


@pytest.mark.asyncio
async def test_an_open_session_is_listed_with_its_activity_and_leaves_without_heartbeats(client, db):
    user_id, workspace, headers = await _open_session(client, db)
    web = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    [item] = (await client.get("/api/v1/mobile/sessions", headers=web)).json()["items"]
    assert item["workspace"]["id"] == workspace and item["profile"] == "governed" and item["activity"] == "working"

    key = headers["x-octryx-session"]
    await note_activity(db, key, "waiting", title="Refactor the pricing", last_text="Done. Shall I run the tests?")
    await note_activity(db, key, "working", title="A later prompt never renames it")
    await db.commit()
    [item] = await open_sessions(db, user_id=user_id)
    assert item["title"] == "Refactor the pricing" and item["last_text"] == "Done. Shall I run the tests?"
    assert item["activity"] == "working"

    row = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == key))).scalar_one()
    row.last_seen_at = utc_now() - timedelta(minutes=3)  # the terminal was closed without a clean end
    await db.commit()
    assert await open_sessions(db, user_id=user_id) == []
    beat = await client.post("/api/v1/agent-gateway/sessions/heartbeat", headers=headers)
    assert beat.status_code == 200 and beat.json() == {"state": "ok"}
    assert len(await open_sessions(db, user_id=user_id)) == 1  # the heartbeat brings it back


@pytest.mark.asyncio
async def test_finalized_and_foreign_sessions_never_show(client, db):
    owner, _workspace_id, headers = await _open_session(client, db, "owner-one")
    other, _other_ws, _other_headers = await _open_session(client, db, "owner-two")
    assert len(await open_sessions(db, user_id=other)) == 1
    mine = await open_sessions(db, user_id=owner)
    assert len(mine) == 1 and mine[0]["id"] not in {item["id"] for item in await open_sessions(db, user_id=other)}
    row = (await db.execute(select(AgentPresence).where(
        AgentPresence.session_key == headers["x-octryx-session"]))).scalar_one()
    row.stopped_at = utc_now()
    await db.commit()
    assert await open_sessions(db, user_id=owner) == []


@pytest.mark.asyncio
async def test_unknown_activities_and_oversized_texts_are_bounded(client, db):
    user_id, _workspace_id, headers = await _open_session(client, db)
    key = headers["x-octryx-session"]
    await note_activity(db, key, "hacking", title="x")
    await note_activity(db, key, "waiting", title="t" * 500, last_text="a" * 10000)
    await db.commit()
    [item] = await open_sessions(db, user_id=user_id)
    assert item["activity"] == "waiting" and len(item["title"]) == 200 and len(item["last_text"]) == 4000


@pytest.mark.asyncio
async def test_the_heartbeat_keeps_the_phone_list_only_never_claims_or_liveness(client, db, monkeypatch):
    # An idle open terminal must neither renew work-item claims nor hold off auto-takeover
    _user_id, _workspace_id, headers = await _open_session(client, db)
    key = headers["x-octryx-session"]
    row = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == key))).scalar_one()
    stale = utc_now() - timedelta(minutes=30)
    row.last_seen_at = stale
    await db.commit()
    import app.services.agent_gateway.presence as presence

    async def no_renewal(*_args, **_kwargs):
        raise AssertionError("a heartbeat must not renew claims")

    monkeypatch.setattr(presence, "renew_gateway_claims", no_renewal)
    assert (await client.post("/api/v1/agent-gateway/sessions/heartbeat", headers=headers)).status_code == 200
    await db.refresh(row)
    assert row.last_seen_at == stale and row.heartbeat_at is not None


@pytest.mark.asyncio
async def test_a_stopped_session_drops_its_answer(client, db):
    from app.services.agent_gateway.presence import stop_presence

    user_id, _workspace_id, headers = await _open_session(client, db)
    key = headers["x-octryx-session"]
    await note_activity(db, key, "waiting", last_text="secret-ish answer")
    await db.commit()
    await stop_presence(db, key)
    await db.commit()
    row = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == key))).scalar_one()
    assert row.last_text is None


@pytest.mark.asyncio
async def test_only_the_main_stop_means_waiting_for_the_person(client, db):
    # A subagent's end leaves the session working
    user_id, _workspace_id, headers = await _open_session(client, db)
    base = "/api/v1/agent-gateway/sessions/verification"
    sub = await client.post(base, headers=headers, json={"hook_event_name": "SubagentStop", "stop_hook_active": False,
                                                         "mobile": {"title": "Subagent run"}})
    assert sub.status_code == 200, sub.text
    [item] = await open_sessions(db, user_id=user_id)
    assert item["activity"] == "working" and item["title"] == "Subagent run"
    main = await client.post(base, headers=headers, json={"hook_event_name": "Stop", "stop_hook_active": False})
    assert main.status_code == 200
    db.expire_all()
    [item] = await open_sessions(db, user_id=user_id)
    assert item["activity"] == "waiting"


@pytest.mark.asyncio
async def test_each_open_session_names_the_engine_it_was_registered_with(client, db):
    # The phone's run line: a Codex terminal session reads as Codex, every other one as Claude Code.
    user_id, workspace, _headers = await _open_session(client, db, "engine-owner")
    codex_headers = await _gateway_headers(db, user_id, workspace)
    registered = await client.post("/api/v1/agent-gateway/sessions/register", headers=codex_headers,
                                   json={"profile": "governed", "client": "octryx-claude", "engine": "codex"})
    assert registered.status_code == 200, registered.text

    items = await open_sessions(db, user_id=user_id)
    assert sorted(item["engine"] for item in items) == ["claude_code", "codex"]
    web = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    listed = (await client.get("/api/v1/mobile/sessions", headers=web)).json()["items"]
    assert sorted(item["engine"] for item in listed) == ["claude_code", "codex"]
