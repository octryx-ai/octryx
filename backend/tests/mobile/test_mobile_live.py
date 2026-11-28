"""Octryx Mobile "live": the owner messages Claude Code sessions running on their own device, through its channel."""

# ruff: noqa: F811  (the shared ``cookie_client`` fixture is imported, then requested by name)
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import DeviceLiveSnapshot, LiveMessage, User
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.devices.live_values import MAX_OPEN, normalize_sessions
from app.time_utils import utc_now
from tests.devices.device_support import RecordingConnection, device_with_grant, user_named
from tests.mobile.mobile_live_support import cookie_client  # noqa: F401 - fixture

PEER = "uds:/tmp/cc-socks/12157.sock"
SESSION = {"peer": PEER, "profile": "default", "pid": 12157, "session_id": "s-1", "name": "octryx-pet",
           "cwd": "/Users/x/PRIV", "status": "busy", "kind": "interactive", "updated_at": 5}


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _reporting_device(db, user, sessions=None, *, live=True):
    device, _ = await device_with_grant(db, user)
    await DeviceJobHandlers().message(db, RecordingConnection(device.id), {
        "type": "live_sessions", "body": {"sessions": [SESSION] if sessions is None else sessions, "live": live}})
    await db.commit()
    return device


@pytest.mark.asyncio
async def test_round_trip_owner_to_session_and_back(cookie_client, db, auth_user):
    device = await _reporting_device(db, auth_user)

    listed = await cookie_client.get("/api/v1/mobile/live")
    assert listed.status_code == 200, listed.text
    [entry] = listed.json()["items"]
    assert entry["device_id"] == device.id and entry["fresh"] is True
    assert entry["sessions"][0]["name"] == "octryx-pet" and entry["sessions"][0]["last_message"] is None

    sent = await cookie_client.post("/api/v1/mobile/live/messages",
                                    json={"device_id": device.id, "peer": PEER, "text": "  Status?  "})
    assert sent.status_code == 202, sent.text
    message_id = sent.json()["message"]["id"]

    connection = RecordingConnection(device.id)
    handlers = DeviceJobHandlers()
    await handlers.tick(db, connection)
    await db.commit()
    live_sends = [body for kind, body in connection.sent if kind == "live_send"]
    assert live_sends == [{"message_id": message_id, "peer": PEER, "text": "Status?",
                           "sender": auth_user.display_name or auth_user.username}]
    await handlers.tick(db, connection)
    assert len([kind for kind, _ in connection.sent if kind == "live_send"]) == 1

    await handlers.message(db, connection, {"type": "live_delivery", "body": {
        "message_id": message_id, "state": "delivered", "reason": ""}})
    await handlers.message(db, connection, {"type": "live_incoming", "body": {
        "from": PEER, "name": "octryx-pet", "text": "All green.", "at": 1}})
    await db.commit()

    thread = await cookie_client.get("/api/v1/mobile/live/messages", params={"device_id": device.id, "peer": PEER})
    assert thread.status_code == 200, thread.text
    data = thread.json()
    assert data["running"] is True
    assert [(item["direction"], item["text"], item["state"]) for item in data["items"]] == [
        ("out", "Status?", "delivered"), ("in", "All green.", "received")]


@pytest.mark.asyncio
async def test_bearer_and_api_key_are_refused(client, db, auth_headers, auth_user):
    device = await _reporting_device(db, auth_user)
    for path in ("/api/v1/mobile/live", "/api/v1/mobile/live/messages"):
        if path.endswith("messages"):
            refused = await client.post(path, headers=auth_headers, json={"device_id": device.id, "peer": PEER,
                                                                          "text": "rm -rf"})
        else:
            refused = await client.get(path, headers=auth_headers)
        assert refused.status_code == 403
        assert refused.json()["reason"] == "interactive_login_required"
    assert (await db.execute(select(LiveMessage))).scalars().all() == []


@pytest.mark.asyncio
async def test_only_listed_running_sessions_of_the_own_device(cookie_client, db, auth_user):
    other = await user_named(db, "someone")
    foreign = await _reporting_device(db, other)
    device = await _reporting_device(db, auth_user)

    async def send(**body):
        payload = {"device_id": device.id, "peer": PEER, "text": "hi", **body}
        return await cookie_client.post("/api/v1/mobile/live/messages", json=payload)

    assert (await send(device_id=foreign.id)).json()["reason"] == "device_not_found"
    assert (await send(peer="uds:/tmp/cc-socks/999.sock")).json()["reason"] == "session_not_running"
    assert (await send(text="")).json()["reason"] == "text_invalid"
    assert (await send(text="x" * 8001)).json()["reason"] == "text_invalid"
    foreign_thread = await cookie_client.get("/api/v1/mobile/live/messages",
                                             params={"device_id": foreign.id, "peer": PEER})
    assert foreign_thread.status_code == 404
    assert [item["device_id"] for item in (await cookie_client.get("/api/v1/mobile/live")).json()["items"]] == [
        device.id]

    snapshot = await db.get(DeviceLiveSnapshot, device.id)
    snapshot.reported_at = utc_now() - timedelta(minutes=10)
    await db.commit()
    assert (await send()).json()["reason"] == "live_unavailable"

    await DeviceJobHandlers().message(db, RecordingConnection(device.id), {
        "type": "live_sessions", "body": {"sessions": [], "live": False}})
    await db.commit()
    assert (await send()).json()["reason"] == "live_unavailable"
    assert (await cookie_client.get("/api/v1/mobile/live")).json()["items"] == []


@pytest.mark.asyncio
async def test_open_messages_are_capped_and_time_out(cookie_client, db, auth_user):
    device = await _reporting_device(db, auth_user)
    for _ in range(MAX_OPEN):
        ok = await cookie_client.post("/api/v1/mobile/live/messages",
                                      json={"device_id": device.id, "peer": PEER, "text": "hi"})
        assert ok.status_code == 202
    capped = await cookie_client.post("/api/v1/mobile/live/messages",
                                      json={"device_id": device.id, "peer": PEER, "text": "hi"})
    assert capped.status_code == 429 and capped.json()["reason"] == "too_many_open"

    connection = RecordingConnection(device.id)
    await DeviceJobHandlers().tick(db, connection)
    for message in (await db.execute(select(LiveMessage))).scalars().all():
        message.updated_at = utc_now() - timedelta(minutes=10)
    await DeviceJobHandlers().tick(db, connection)
    await db.commit()
    states = {(m.state, m.reason) for m in (await db.execute(select(LiveMessage))).scalars().all()}
    assert states == {("failed", "no_answer")}


@pytest.mark.asyncio
async def test_device_reports_are_normalized_and_bound_to_the_device(db, auth_user):
    other = await user_named(db, "someone")
    device = await _reporting_device(db, auth_user)
    foreign = await _reporting_device(db, other)
    handlers = DeviceJobHandlers()
    message = LiveMessage(owner_user_id=auth_user.id, device_id=device.id, peer=PEER, direction="out", text="hi",
                          state="sent", created_at=utc_now(), updated_at=utc_now())
    db.add(message)
    await db.flush()
    await handlers.message(db, RecordingConnection(foreign.id), {"type": "live_delivery", "body": {
        "message_id": message.id, "state": "delivered"}})
    await handlers.message(db, RecordingConnection(device.id), {"type": "live_delivery", "body": {
        "message_id": message.id, "state": "pwned"}})
    assert message.state == "sent"
    await handlers.message(db, RecordingConnection(device.id), {"type": "live_incoming", "body": {
        "from": "uds:/tmp/../../etc/passwd x", "text": "hi"}})
    assert len((await db.execute(select(LiveMessage))).scalars().all()) == 1

    cleaned = normalize_sessions([
        {**SESSION, "pid": "1; rm", "profile": "Pri<v>ate!", "extra": "dropped"},
        {**SESSION},
        {"peer": "uds:relative.sock"},
        "junk",
    ])
    assert len(cleaned) == 1
    assert cleaned[0]["pid"] == 0 and cleaned[0]["profile"] == "private" and "extra" not in cleaned[0]
    # the session's coding engine: Codex when reported, Claude Code when not reported and for anything unknown
    assert cleaned[0]["engine"] == "claude_code"
    assert normalize_sessions([{**SESSION, "engine": "codex"}])[0]["engine"] == "codex"
    assert normalize_sessions([{**SESSION, "engine": "gpt"}])[0]["engine"] == "claude_code"
    # the session's model (the phone's run line): a narrow id when reported, else ""
    assert cleaned[0]["model"] == ""
    assert normalize_sessions([{**SESSION, "model": "claude-opus-5-5[1m]"}])[0]["model"] == "claude-opus-5-5[1m]"
    assert normalize_sessions([{**SESSION, "model": "gpt-5.1-codex"}])[0]["model"] == "gpt-5.1-codex"
    assert normalize_sessions([{**SESSION, "model": "<script>"}])[0]["model"] == ""
    assert normalize_sessions([{**SESSION, "model": 42}])[0]["model"] == ""


@pytest.mark.asyncio
async def test_kill_switch_and_pause_stop_live_texts(cookie_client, db, auth_user):
    from app.services.devices.platform_switch import set_device_runs_platform_enabled

    device = await _reporting_device(db, auth_user)
    device_id = device.id
    queued = await cookie_client.post("/api/v1/mobile/live/messages",
                                      json={"device_id": device_id, "peer": PEER, "text": "queued before"})
    assert queued.status_code == 202

    await set_device_runs_platform_enabled(db, enabled=False, actor_id=auth_user.id)
    await db.commit()
    refused = await cookie_client.post("/api/v1/mobile/live/messages",
                                       json={"device_id": device_id, "peer": PEER, "text": "hi"})
    assert refused.status_code == 403 and refused.json()["reason"] == "device_runs_platform_disabled"
    connection = RecordingConnection(device_id)
    await DeviceJobHandlers().tick(db, connection)
    await db.commit()
    assert [kind for kind, _ in connection.sent if kind == "live_send"] == []
    stopped = (await db.execute(select(LiveMessage))).scalars().one()
    assert (stopped.state, stopped.reason) == ("failed", "device_runs_platform_disabled")

    await set_device_runs_platform_enabled(db, enabled=True, actor_id=auth_user.id)
    device = await db.get(type(device), device_id)
    device.paused = True
    await db.commit()
    paused = await cookie_client.post("/api/v1/mobile/live/messages",
                                      json={"device_id": device_id, "peer": PEER, "text": "hi"})
    assert paused.status_code == 403 and paused.json()["reason"] == "device_paused"
