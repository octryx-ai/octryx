"""A refused refresh, a 4401, a confirmed revoke, a garbled handshake and an unexpected error in the channel."""

from __future__ import annotations

import asyncio
import json

import pytest

from octryx_claude import device_state
from octryx_claude.device_channel import ChannelClient
from octryx_claude.device_channel_wire import ChannelClosedError
from octryx_claude.tokens import TokenUnavailableError
from tests.device_channel_support import FakeConnection, FakePlatform, _client, _enabled, _handshake


class RawConnection(FakeConnection):
    """Sends the given texts verbatim (a garbled frame) before the scripted messages."""

    def __init__(self, *raw: str) -> None:
        super().__init__()
        self.raw = list(raw)

    async def recv(self) -> str:
        if self.raw and self.to_device.empty():
            await asyncio.sleep(0)
        item = await self.to_device.get()
        if isinstance(item, str):
            return item
        if isinstance(item, ChannelClosedError):
            raise item
        return json.dumps(item)


@pytest.mark.asyncio
async def test_a_refused_refresh_idles_as_needs_login_without_connecting(state):
    _enabled(state)
    platform = FakePlatform()
    sleeps: list[float] = []

    def provider(force: bool) -> str:
        raise TokenUnavailableError("refresh_rejected")

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await asyncio.sleep(0)

    client = ChannelClient(state, token_provider=provider, report=dict, connect=platform, sleep=sleep)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    for _ in range(20):
        await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(runner, 2)
    assert platform.urls == []
    assert set(sleeps) == {60.0}
    assert device_state.read_status(state)["needs_login"] is False  # cleared when the idle ended (stop)


@pytest.mark.asyncio
async def test_a_4401_forces_one_refresh_then_idles(state):
    _enabled(state)
    platform = FakePlatform(ChannelClosedError(4401, "device_token_invalid"),
                            ChannelClosedError(4401, "device_token_invalid"))
    tokens: list[bool] = []
    client = _client(state, platform, tokens=tokens)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    for _ in range(30):
        await asyncio.sleep(0)
    assert tokens[:2] == [False, True]
    assert len(platform.urls) == 2
    assert client.idle_reason == "needs_login"
    assert device_state.read_status(state)["needs_login"] is True
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_a_confirmed_revoke_marks_the_device_revoked_and_stops_connecting(state):
    _enabled(state)
    connection = FakeConnection()
    platform = FakePlatform(connection)
    asked: list[str] = []
    client = _client(state, platform, confirm_revoked=lambda: asked.append("check") or "revoked")
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(connection, state)
    connection.push("revoke")
    for _ in range(30):
        await asyncio.sleep(0)
    assert asked == ["check"]
    assert device_state.load_device(state)["revoked"] is True
    assert client.idle_reason == "revoked" and len(platform.urls) == 1
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_a_slow_or_garbled_handshake_reconnects_instead_of_ending_the_service(state, monkeypatch):
    """A challenge that does not arrive within the handshake timeout (a slow platform) or a garbled welcome makes the
    service reconnect; neither ends it."""
    import octryx_claude.device_channel_wire as channel

    monkeypatch.setattr(channel, "HANDSHAKE_TIMEOUT", 0.05)
    _enabled(state)
    silent = FakeConnection()  # never sends the challenge
    garbled = RawConnection()
    garbled.push("challenge", {"nonce": "n-1"})
    garbled.to_device.put_nowait("{not json")
    healthy = FakeConnection()
    platform = FakePlatform(silent, garbled, healthy)
    client = _client(state, platform)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(healthy, state)
    for _ in range(50):
        await asyncio.sleep(0.01)
        if client.connected:
            break
    assert client.connected and len(platform.urls) == 3 and not runner.done()
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_an_unexpected_error_in_an_attempt_is_logged_and_retried(state, caplog):
    _enabled(state)
    connection = FakeConnection()
    platform = FakePlatform(connection)
    calls: list[bool] = []

    def provider(force: bool) -> str:
        calls.append(force)
        if len(calls) == 1:
            raise RuntimeError("credential file busy")
        return "channel-token"

    async def sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    client = ChannelClient(state, token_provider=provider, report=lambda: {"folders": [], "paused": False},
                           connect=platform, sleep=sleep, jitter=lambda: 0.5)
    stop = asyncio.Event()
    with caplog.at_level("ERROR", logger="octryx_claude.device"):
        runner = asyncio.create_task(client.run_forever(stop))
        await _handshake(connection, state)
        await asyncio.sleep(0.01)
    assert client.connected and len(calls) >= 2  # the first attempt failed, a later one connected
    assert any("RuntimeError" in record.getMessage() and record.exc_info for record in caplog.records)
    stop.set()
    await asyncio.wait_for(runner, 2)
