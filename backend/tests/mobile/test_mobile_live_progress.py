"""Live progress: what a listed session is doing, numbered per session, caught up with
``since_seq``; only the owner, only by the interactive login, only a session listed right now."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import LiveProgressEvent
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.devices.live_progress import KEEP_PER_SESSION, normalize_event
from app.services.mobile.session import phone_may_use
from tests.devices.device_support import RecordingConnection, user_named
from tests.mobile.mobile_live_support import cookie_client  # noqa: F401 - fixture
from tests.mobile.test_mobile_live import PEER, _admin, _reporting_device

API = "/api/v1/mobile/live/progress"


async def _report(db, device, events, peer=PEER):
    await DeviceJobHandlers().message(db, RecordingConnection(device.id), {
        "type": "live_progress", "body": {"peer": peer, "events": events}})
    await db.commit()


@pytest.mark.asyncio
async def test_events_are_numbered_and_caught_up_since_a_seq(cookie_client, db):  # noqa: F811
    owner = await _admin(db)
    device = await _reporting_device(db, owner)
    await _report(db, device, [
        {"kind": "text", "text": "Running the tests."},
        {"kind": "tool", "id": "t1", "tool": "Bash", "input": "npm test"},
        {"kind": "result", "id": "t1", "ok": False, "line": "2 failing"},
    ])
    first = await cookie_client.get(API, params={"device_id": device.id, "peer": PEER})
    assert first.status_code == 200, first.text
    data = first.json()
    assert [(e["seq"], e["kind"]) for e in data["events"]] == [(1, "text"), (2, "tool"), (3, "result")]
    assert data["events"][2]["ok"] is False and data["last_seq"] == 3 and data["running"] is True
    assert data["status"] == "busy"
    await _report(db, device, [{"kind": "text", "text": "Fixed it."}])
    delta = (await cookie_client.get(API, params={"device_id": device.id, "peer": PEER, "since_seq": 3})).json()
    assert [(e["seq"], e["text"]) for e in delta["events"]] == [(4, "Fixed it.")]


@pytest.mark.asyncio
async def test_only_listed_sessions_known_kinds_and_redacted_texts(cookie_client, db):  # noqa: F811
    owner = await _admin(db)
    device = await _reporting_device(db, owner)
    await _report(db, device, [{"kind": "text", "text": "hi"}], peer="uds:/tmp/cc-socks/999.sock")  # not listed
    await _report(db, device, [
        {"kind": "thinking", "text": "never stored"},
        {"kind": "text", "text": "token=ghp_" + "a" * 40, "secret_field": "dropped"},
        {"kind": "result", "id": "t", "line": "x" * 500},
        "not an event",
    ])
    rows = (await db.execute(select(LiveProgressEvent).order_by(LiveProgressEvent.seq))).scalars().all()
    assert [row.peer for row in rows] == [PEER, PEER]
    assert "ghp_" not in rows[0].body["text"] and "secret_field" not in rows[0].body
    assert len(rows[1].body["line"]) == 160 and rows[1].body["ok"] is True
    gone = await cookie_client.get(API, params={"device_id": device.id, "peer": "uds:/tmp/cc-socks/999.sock"})
    assert gone.status_code == 409 and gone.json()["reason"] == "session_not_running"


@pytest.mark.asyncio
async def test_only_the_owner_by_interactive_login(cookie_client, client, db, auth_headers):  # noqa: F811
    owner = await _admin(db)
    other = await user_named(db, "someone")
    foreign = await _reporting_device(db, other)
    await _report(db, foreign, [{"kind": "text", "text": "theirs"}])
    refused = await cookie_client.get(API, params={"device_id": foreign.id, "peer": PEER})
    assert refused.status_code == 404
    device = await _reporting_device(db, owner)
    cookie_client.cookies.clear()
    bearer = await client.get(API, params={"device_id": device.id, "peer": PEER}, headers=auth_headers)
    assert bearer.status_code == 403 and bearer.json()["reason"] == "interactive_login_required"


@pytest.mark.asyncio
async def test_only_the_newest_events_per_session_are_kept(cookie_client, db):  # noqa: F811
    owner = await _admin(db)
    device = await _reporting_device(db, owner)
    for _ in range(KEEP_PER_SESSION // 50 + 2):
        await _report(db, device, [{"kind": "text", "text": "step"}] * 50)
    seqs = [row.seq for row in (await db.execute(select(LiveProgressEvent))).scalars().all()]
    assert len(seqs) == KEEP_PER_SESSION and max(seqs) == (KEEP_PER_SESSION // 50 + 2) * 50


def test_the_phone_may_read_progress_and_nothing_else_new():
    assert phone_may_use("GET", "/api/v1/mobile/live/progress") is True
    assert phone_may_use("POST", "/api/v1/mobile/live/progress") is False
    assert phone_may_use("GET", "/api/v1/mobile/live/progress/x") is False


def test_events_are_normalized_to_a_closed_shape():
    assert normalize_event({"kind": "tool", "tool": "Bash", "input": "ls", "extra": 1}) == {
        "kind": "tool", "tool": "Bash", "input": "ls"}
    assert normalize_event({"kind": "nope"}) is None
    assert normalize_event({"kind": "compact", "at": "2026-11-09T08:00:00Z"}) == {
        "kind": "compact", "at": "2026-11-09T08:00:00Z"}
