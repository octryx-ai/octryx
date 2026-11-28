"""The device channel stays truthful under faults."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.models.security.device import DEVICE_STATUS_REVOKED
from app.services.devices import channel as channel_module
from app.services.devices import channel_protocol
from app.services.devices.channel import DeviceChannelSession
from app.services.devices.channel_protocol import CLOSE_INTERNAL, CLOSE_REVOKED, ChannelHandlers
from app.services.devices.credential import revoke_device_grant
from app.services.devices.hub import device_hub, device_revoked
from tests.devices.device_support import FakeSocket, SharedSession, keyed_device, signed_hello, user_named


class FlakyHandlers(ChannelHandlers):
    def __init__(self, failures: int | None) -> None:
        self.failures = failures
        self.calls = 0
        self.healthy_rounds = 0

    async def tick(self, db, connection) -> None:
        self.calls += 1
        if self.failures is None or self.calls <= self.failures:
            raise RuntimeError("database unavailable")
        self.healthy_rounds += 1


@pytest.fixture(autouse=True)
def _fast_ticks(monkeypatch):
    monkeypatch.setattr(channel_module, "TICK_SECONDS", 0.01)
    monkeypatch.setattr(channel_module, "TICK_BACKOFF_MAX_SECONDS", 0.02, raising=False)
    device_hub.clear()
    yield
    device_hub.clear()


async def _connected(db, handlers, *, clock=time.time):
    user = await user_named(db, "device-owner")
    device, private, token = await keyed_device(db, user)
    socket = FakeSocket()
    session = DeviceChannelSession(socket, token=token, session_factory=SharedSession(db), handlers=handlers,
                                   clock=clock)
    task = asyncio.create_task(session.run())
    challenge = await socket.next()
    await socket.incoming.put(signed_hello(private, device.id, challenge["body"]["nonce"]))
    assert (await socket.next())["type"] == "welcome"
    return device, socket, session, task


async def _until(predicate, seconds: float = 3.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_device_channel_tick_failure_is_survived_and_the_ticker_keeps_running(db):
    handlers = FlakyHandlers(failures=2)
    device, socket, session, task = await _connected(db, handlers)

    await _until(lambda: handlers.healthy_rounds >= 3)  # the ticker went on after two failing rounds

    assert socket.closed is None and not task.done()
    assert device_hub.connected(device.id)
    await socket.incoming.put(None)
    await asyncio.wait_for(task, 2)


@pytest.mark.asyncio
async def test_device_channel_tick_failure_that_persists_closes_the_socket_so_the_device_reconnects(db,
                                                                                                    monkeypatch):
    monkeypatch.setattr(channel_module, "TICK_FAILURES_MAX", 3, raising=False)
    handlers = FlakyHandlers(failures=None)
    device, socket, _session, task = await _connected(db, handlers)

    await asyncio.wait_for(task, 3)

    assert socket.closed == (CLOSE_INTERNAL, "device_channel_error")
    assert handlers.calls == 3
    assert not device_hub.connected(device.id)


@pytest.mark.asyncio
async def test_device_channel_tick_task_that_dies_closes_the_socket(db, monkeypatch):
    async def broken_tick_loop(self, connection):
        raise RuntimeError("bug outside the per-round guard")

    monkeypatch.setattr(DeviceChannelSession, "_tick_loop", broken_tick_loop)
    device, socket, _session, task = await _connected(db, ChannelHandlers())

    await asyncio.wait_for(task, 2)

    assert socket.closed == (CLOSE_INTERNAL, "device_channel_error")
    assert not device_hub.connected(device.id)


@pytest.mark.asyncio
async def test_a_connection_whose_tick_stopped_succeeding_is_not_counted_as_connected(db):
    device, socket, session, task = await _connected(db, ChannelHandlers())
    assert device_hub.connected(device.id)

    session.connection.last_tick_at = time.monotonic() - channel_protocol.STALE_AFTER_SECONDS - 1
    assert not device_hub.connected(device.id)
    assert device_hub.attached(device.id) is session.connection
    await device_revoked(device.id)
    await asyncio.wait_for(task, 2)
    assert socket.closed == (CLOSE_REVOKED, "revoke")


class _Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_a_revoked_grant_closes_as_a_token_problem_not_as_a_revocation(db):
    clock = _Clock()
    device, socket, session, task = await _connected(db, ChannelHandlers(), clock=clock)

    async with session.session_factory() as shared:  # not while a tick uses the session
        await revoke_device_grant(shared, device.grant_id)  # a refresh replay ended the grant; the device is active
    clock.now += channel_module.RECHECK_SECONDS + 1
    await asyncio.wait_for(task, 2)

    assert socket.closed == (1000, "device_grant_revoked")
    sent = []
    while not socket.outgoing.empty():
        sent.append(socket.outgoing.get_nowait()["type"])
    assert "revoke" not in sent


@pytest.mark.asyncio
async def test_a_revoked_device_still_closes_as_revoke(db):
    clock = _Clock()
    device, socket, session, task = await _connected(db, ChannelHandlers(), clock=clock)

    async with session.session_factory() as shared:  # not while a tick uses the session
        device.status = DEVICE_STATUS_REVOKED
        await shared.flush()
    clock.now += channel_module.RECHECK_SECONDS + 1
    await asyncio.wait_for(task, 2)

    assert socket.closed == (CLOSE_REVOKED, "revoke")


@pytest.mark.asyncio
async def test_a_failing_recheck_is_retried_on_the_next_round_not_skipped_for_thirty_seconds(db, monkeypatch):
    clock = _Clock()
    device, socket, session, task = await _connected(db, ChannelHandlers(), clock=clock)
    original = session._credential
    calls: list[str] = []

    async def flaky_credential(token):
        calls.append(token)
        if len(calls) == 1:
            raise RuntimeError("database unavailable")
        return await original(token)

    monkeypatch.setattr(session, "_credential", flaky_credential)
    async with session.session_factory() as shared:  # not while a tick uses the session
        device.status = DEVICE_STATUS_REVOKED
        await shared.flush()
    clock.now += channel_module.RECHECK_SECONDS + 1
    await asyncio.wait_for(task, 2)  # no further clock advance needed: the failed check runs again

    assert len(calls) == 2
    assert socket.closed == (CLOSE_REVOKED, "revoke")
