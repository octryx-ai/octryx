"""The device channel client: signed handshake, replay after reconnect without gaps or duplicates,
backoff with jitter, token hand-over, and no retry storm when the login is gone or the device is revoked."""

from __future__ import annotations

import asyncio

import pytest

from octryx_claude import device_state
from octryx_claude.device_channel_wire import ChannelClosedError, channel_url
from octryx_claude.device_outbox import Outbox
from tests.device_channel_support import DEVICE_ID, FakeConnection, FakePlatform, _client, _enabled, _handshake


def test_channel_url_never_carries_the_token():
    assert channel_url("https://octryx.example.test") == "wss://octryx.example.test/api/v1/devices/channel"
    assert channel_url("http://localhost:8000") == "ws://localhost:8000/api/v1/devices/channel"


@pytest.mark.asyncio
async def test_handshake_is_signed_and_reconnect_replays_only_what_the_platform_lacks(state):
    _enabled(state)
    outbox = Outbox(state)
    for index in range(3):
        outbox.append("dj_1", "job_event", {"n": index + 1})
    connection = FakeConnection()
    platform = FakePlatform(connection)
    client = _client(state, platform)
    client.outbox = outbox
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    hello = await _handshake(connection, state, streams={"dj_1": 2})
    assert hello["body"]["device_id"] == DEVICE_ID
    assert platform.headers[0] == {"Authorization": "Bearer channel-token-1"}
    replayed = await connection.next()
    assert (replayed["stream"], replayed["seq"], replayed["body"]) == ("dj_1", 3, {"n": 3})
    assert [entry["seq"] for entry in outbox.pending("dj_1")] == [3]

    await client.send_job("dj_1", "job_event", {"n": 4})
    assert (await connection.next())["seq"] == 4
    connection.push("nack", {"stream": "dj_1", "expected": 3})
    assert [(await connection.next())["seq"] for _ in range(2)] == [3, 4]
    connection.push("ack", {"stream": "dj_1", "seq": 4})
    await asyncio.sleep(0.01)
    assert outbox.pending("dj_1") == []
    assert device_state.read_status(state)["connected"] is True

    stop.set()
    await asyncio.wait_for(runner, 2)
    # The buffer survives a restart without repeating a seq.
    assert Outbox(state).append("dj_1", "job_event", {})["seq"] == 5


@pytest.mark.asyncio
async def test_backoff_doubles_with_jitter_and_resets_after_a_connection(state):
    _enabled(state)
    connection = FakeConnection()
    platform = FakePlatform(ChannelClosedError(1006), ChannelClosedError(1006), connection,
                            ChannelClosedError(1006))
    sleeps: list[float] = []
    client = _client(state, platform, sleeps=sleeps)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(connection, state)
    await asyncio.sleep(0.01)
    assert sleeps[:2] == [1.0, 2.0]  # jitter 0.5 → factor 1.0
    connection.to_device.put_nowait(ChannelClosedError(1006, "gone"))
    for _ in range(50):
        await asyncio.sleep(0)
        if len(platform.urls) >= 4:
            break
    stop.set()
    await asyncio.wait_for(runner, 2)
    reconnect_sleeps = [value for value in sleeps if value != 5.0]  # 5.0: the state-check timer
    assert reconnect_sleeps[2] == 1.0  # it was connected: back to 1 s


@pytest.mark.asyncio
async def test_pause_resume_and_job_messages_reach_the_manager(state):
    _enabled(state)
    connection = FakeConnection()
    seen: list[str] = []

    async def on_message(message_type: str, body: dict) -> None:
        seen.append(message_type)

    client = _client(state, FakePlatform(connection), on_message=on_message)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(connection, state, paused=True)
    await asyncio.sleep(0.01)
    assert client.paused is True
    connection.push("resume")
    connection.push("job_offer", {"job_id": "dj_1"})
    await asyncio.sleep(0.01)
    assert client.paused is False
    assert seen == ["connected", "resume", "job_offer"]
    device = device_state.load_device(state)
    device["paused"] = True
    device_state.save_device(state, device)
    assert client.paused is True  # the local pause works whatever the platform says
    stop.set()
    await asyncio.wait_for(runner, 2)
