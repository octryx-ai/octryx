"""The device channel: token + signed-nonce handshake, sequenced events stored exactly once, token
replacement without reconnect, and pause/revoke pushed to the connected device."""

from __future__ import annotations

import asyncio

import pytest

from app.models import UserDevice
from app.services.devices.channel import DeviceChannelSession
from app.services.devices.channel_protocol import (
    CLOSE_FORBIDDEN,
    CLOSE_UNAUTHORIZED,
    RESULT_DUPLICATE,
    RESULT_STORED,
    ChannelHandlers,
    envelope,
)
from app.services.devices.credential import revoke_device_grant
from app.services.devices.hub import device_hub, device_revoked, devices_paused
from tests.devices.device_support import FakeSocket, SharedSession, keyed_device, signed_hello, user_named


class RecordingHandlers(ChannelHandlers):
    def __init__(self) -> None:
        self.stored: dict[str, int] = {}
        self.messages: list[dict] = []

    async def welcome_streams(self, db, device):
        return dict(self.stored)

    async def stream_event(self, db, connection, message):
        last = self.stored.get(message["stream"], 0)
        if message["seq"] <= last:
            return RESULT_DUPLICATE
        if message["seq"] != last + 1:
            return last + 1
        self.stored[message["stream"]] = message["seq"]
        return RESULT_STORED

    async def message(self, db, connection, message):
        self.messages.append(message)


async def _connect(db, socket, token, handlers=None):
    session = DeviceChannelSession(socket, token=token, session_factory=SharedSession(db),
                                   handlers=handlers or RecordingHandlers())
    return session, asyncio.create_task(session.run())


@pytest.fixture(autouse=True)
def _empty_hub():
    device_hub.clear()
    yield
    device_hub.clear()


@pytest.mark.asyncio
async def test_signed_handshake_reports_state_and_sequences_events_exactly_once(db):
    user = await user_named(db, "device-owner")
    device, private, token = await keyed_device(db, user)
    socket, handlers = FakeSocket(), RecordingHandlers()
    handlers.stored["dj_known"] = 3
    _session, task = await _connect(db, socket, token, handlers)

    challenge = await socket.next()
    assert challenge["type"] == "challenge"
    await socket.incoming.put(signed_hello(private, device.id, challenge["body"]["nonce"],
                                           folders=["/home/sample/src", "/home/sample/new"], seat_login=True,
                                           max_parallel_jobs=2))
    welcome = await socket.next()
    assert welcome["type"] == "welcome" and welcome["body"]["streams"] == {"dj_known": 3}
    assert device_hub.connected(device.id) and device_hub.connection(device.id).seat_login is True
    refreshed = await db.get(UserDevice, device.id)
    assert refreshed.folders == ["/home/sample/src", "/home/sample/new"] and refreshed.max_parallel_jobs == 2

    for seq, expected in ((1, ("ack", 1)), (1, ("ack", 1)), (3, ("nack", 2)), (2, ("ack", 2))):
        await socket.incoming.put(envelope("job_event", {"kind": "text_delta"}, stream="dj_new", seq=seq))
        answer = await socket.next()
        value = answer["body"].get("seq", answer["body"].get("expected"))
        assert (answer["type"], value) == expected
    assert handlers.stored["dj_new"] == 2

    await socket.incoming.put(envelope("job_accepted", {"job_id": "dj_new"}))
    await socket.incoming.put(envelope("ping"))
    assert (await socket.next())["type"] == "pong"
    assert handlers.messages[0]["type"] == "job_accepted"

    await socket.incoming.put(None)
    await asyncio.wait_for(task, 2)
    assert not device_hub.connected(device.id)


@pytest.mark.asyncio
async def test_the_codex_seat_login_is_reported_in_hello_and_state_as_yes_or_no(db):
    # The device says whether the Codex seat (the person's own ChatGPT login) is signed in, like seat_login.
    from app.services.devices.hub import device_live_state

    user = await user_named(db, "device-owner")
    device, private, token = await keyed_device(db, user)
    socket = FakeSocket()
    _session, task = await _connect(db, socket, token)
    challenge = await socket.next()
    await socket.incoming.put(signed_hello(private, device.id, challenge["body"]["nonce"], codex_seat_login=True))
    await socket.next()  # welcome
    assert device_live_state(device.id) == {"connected": True, "seat_login": False, "codex_seat_login": True,
                                            "tools": {}}
    # The launcher's pinned tools come with ``state`` too (the review bot chooses a device by them).
    await socket.incoming.put(envelope("state", {"tools": {"gitleaks": "8.30.1", "ast-grep": None}}))
    await socket.incoming.put(envelope("ping"))
    assert (await socket.next())["type"] == "pong"
    assert device_live_state(device.id)["tools"] == {"gitleaks": "8.30.1", "ast-grep": None}

    await socket.incoming.put(envelope("state", {"codex_seat_login": "yes"}))  # anything but true is no
    await socket.incoming.put(envelope("ping"))
    assert (await socket.next())["type"] == "pong"
    assert device_live_state(device.id)["codex_seat_login"] is False
    await socket.incoming.put(envelope("state", {"folders": ["/home/sample/src"]}))  # absent: unchanged
    await socket.incoming.put(envelope("state", {"codex_seat_login": True}))
    await socket.incoming.put(envelope("ping"))
    assert (await socket.next())["type"] == "pong"
    assert device_live_state(device.id)["codex_seat_login"] is True

    await socket.incoming.put(None)
    await asyncio.wait_for(task, 2)
    assert device_live_state(device.id) == {"connected": False, "seat_login": False, "codex_seat_login": False,
                                            "tools": {}}


@pytest.mark.asyncio
async def test_a_wrong_key_or_another_device_id_never_connects(db):
    user = await user_named(db, "device-owner")
    device, _private, token = await keyed_device(db, user)
    _other, other_private, _other_token = await keyed_device(db, user, name="Other")
    socket = FakeSocket()
    _session, task = await _connect(db, socket, token)
    challenge = await socket.next()
    await socket.incoming.put(signed_hello(other_private, device.id, challenge["body"]["nonce"]))
    await asyncio.wait_for(task, 2)
    assert socket.closed == (CLOSE_FORBIDDEN, "device_signature_invalid")
    assert not device_hub.connected(device.id)

    socket = FakeSocket()
    _session, task = await _connect(db, socket, token)
    challenge = await socket.next()
    await socket.incoming.put(signed_hello(other_private, _other.id, challenge["body"]["nonce"]))
    await asyncio.wait_for(task, 2)
    assert socket.closed[1] == "hello_invalid"


@pytest.mark.asyncio
async def test_invalid_or_revoked_credentials_are_closed_before_any_challenge(db):
    user = await user_named(db, "device-owner")
    device, _private, token = await keyed_device(db, user)
    socket = FakeSocket()
    _session, task = await _connect(db, socket, "not-a-token")
    await asyncio.wait_for(task, 2)
    assert socket.closed == (CLOSE_UNAUTHORIZED, "device_token_invalid") and socket.outgoing.empty()

    await revoke_device_grant(db, device.grant_id)
    socket = FakeSocket()
    _session, task = await _connect(db, socket, token)
    await asyncio.wait_for(task, 2)
    assert socket.closed == (CLOSE_UNAUTHORIZED, "device_grant_revoked")


@pytest.mark.asyncio
async def test_pause_resume_and_revoke_reach_the_connected_device(db):
    user = await user_named(db, "device-owner")
    device, private, token = await keyed_device(db, user)
    socket = FakeSocket()
    _session, task = await _connect(db, socket, token)
    challenge = await socket.next()
    await socket.incoming.put(signed_hello(private, device.id, challenge["body"]["nonce"]))
    await socket.next()  # welcome

    await devices_paused([device], paused=True)
    assert (await socket.next())["type"] == "pause"
    await devices_paused([device], paused=False)
    assert (await socket.next())["type"] == "resume"
    await device_revoked(device.id)
    assert (await socket.next())["type"] == "revoke"
    await asyncio.wait_for(task, 2)
    assert socket.closed[1] == "revoke"


@pytest.mark.asyncio
async def test_token_replacement_keeps_the_connection_and_a_foreign_token_closes_it(db):
    user = await user_named(db, "device-owner")
    device, private, token = await keyed_device(db, user)
    _other, _other_private, other_token = await keyed_device(db, user, name="Other")
    socket = FakeSocket()
    session, task = await _connect(db, socket, token)
    challenge = await socket.next()
    await socket.incoming.put(signed_hello(private, device.id, challenge["body"]["nonce"]))
    await socket.next()

    await socket.incoming.put(envelope("token", {"access_token": token}))
    await socket.incoming.put(envelope("ping"))
    assert (await socket.next())["type"] == "pong"
    assert session.connection is not None and not session.connection.closed.is_set()

    await socket.incoming.put(envelope("token", {"access_token": other_token}))
    await asyncio.wait_for(task, 2)
    assert socket.closed is not None
    assert not device_hub.connected(device.id)


def test_only_the_owner_sees_whether_the_codex_seat_is_signed_in():
    from app.services.devices.registry_view import serialize_device

    device = UserDevice(id="d1", owner_user_id="u1", name="Mac", name_key="mac", os="macos", public_key="k",
                        status="active", profiles=["governed", "seat"])
    live = {"connected": True, "seat_login": False, "codex_seat_login": True}
    assert serialize_device(device, owner_view=True, live=live)["codex_seat_login"] is True
    assert "codex_seat_login" not in serialize_device(device, owner_view=False, live=live)
