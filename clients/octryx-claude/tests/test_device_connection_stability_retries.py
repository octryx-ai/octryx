"""Failed attempts logged and reported, retries after restarts, prompt stop, responsive loop, device report."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from octryx_claude import device_runtime, device_state
from octryx_claude.device_channel import ChannelClient
from octryx_claude.device_channel_wire import FAST_RETRY_SECONDS, IDLE_CHECK_SECONDS, ChannelClosedError
from octryx_claude.tokens import TokenUnavailableError
from tests.device_channel_support import FakeConnection, FakePlatform, _client, _enabled, _handshake
from tests.device_connection_stability_support import _revoked_locally, _until


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- D4 -----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unreachable_platform_is_logged_and_reported(state, caplog):
    _enabled(state)
    connection = FakeConnection()
    failures = iter([TokenUnavailableError("platform_unreachable")] * 3)

    def provider(force: bool) -> str:
        error = next(failures, None)
        if error is not None:
            raise error
        return "channel-token"

    statuses: list[dict] = []

    async def sleep(seconds: float) -> None:
        statuses.append(dict(device_state.read_status(state)))
        await asyncio.sleep(0)

    client = ChannelClient(state, token_provider=provider, report=dict, connect=FakePlatform(connection),
                           sleep=sleep, jitter=lambda: 0.5, clock=FakeClock())
    caplog.set_level(logging.INFO, logger="octryx_claude.device")
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    await _handshake(connection, state)

    lines = [record.getMessage() for record in caplog.records if "platform_unreachable" in record.getMessage()]
    assert len(lines) == 1  # three failures within a minute: one line
    assert "attempt 1" in lines[0]
    assert [status["attempt"] for status in statuses[:3]] == [1, 2, 3]
    assert {status["last_error"] for status in statuses[:3]} == {"platform_unreachable"}
    assert all(status["next_retry_at"] > time.time() - 5 for status in statuses[:3])
    await _until(lambda: device_state.read_status(state).get("connected") is True)
    assert device_state.read_status(state)["last_error"] == "" and device_state.read_status(state)["attempt"] == 0
    stop.set()
    await asyncio.wait_for(runner, 2)


# --- D5 -----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_after_an_announced_restart_the_device_retries_every_few_seconds(state):
    _enabled(state)
    first, last = FakeConnection(), FakeConnection()
    outcomes = [first] + [ChannelClosedError(1006, "unreachable")] * 6 + [last]
    clock = FakeClock()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds
        await asyncio.sleep(0)

    client = ChannelClient(state, token_provider=lambda force: "t", report=dict, connect=FakePlatform(*outcomes),
                           sleep=sleep, jitter=lambda: 0.5, clock=clock)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(first, state)
    await _until(lambda: client.connected)
    sleeps.clear()

    first.to_device.put_nowait(ChannelClosedError(1012, "service restart"))
    await _handshake(last, state)

    retries = [value for value in sleeps if value != 5.0]
    assert retries == [FAST_RETRY_SECONDS] * 7  # not 1, 2, 4, 8, 16, 30, 30
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_unannounced_failures_still_back_off_exponentially_up_to_thirty_seconds(state):
    _enabled(state)
    last = FakeConnection()
    sleeps: list[float] = []
    client = _client(state, FakePlatform(*[ChannelClosedError(1006, "unreachable")] * 7, last), sleeps=sleeps)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    await _handshake(last, state)

    assert sleeps[:7] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    stop.set()
    await asyncio.wait_for(runner, 2)


# --- D6 -----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_returns_promptly_on_stop(state):
    _enabled(state)
    _revoked_locally(state)
    client = ChannelClient(state, token_provider=lambda force: "t", report=dict, connect=FakePlatform(),
                           sleep=asyncio.sleep)  # real sleeps: an idle round is IDLE_CHECK_SECONDS long
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _until(lambda: client.idle_reason == "revoked")

    started = time.monotonic()
    stop.set()
    await asyncio.wait_for(runner, 2)

    assert time.monotonic() - started < 1.0 < IDLE_CHECK_SECONDS


# --- D8 -----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_loop_stays_responsive_while_the_token_provider_blocks(state):
    _enabled(state)
    connection = FakeConnection()

    def slow_provider(force: bool) -> str:
        time.sleep(0.3)  # an HTTP refresh, a held credential file lock
        return "channel-token"

    client = ChannelClient(state, token_provider=slow_provider, report=dict, connect=FakePlatform(connection),
                           sleep=asyncio.sleep, jitter=lambda: 0.5)
    beats: list[float] = []

    async def heartbeat() -> None:
        while True:
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    beat = asyncio.create_task(heartbeat())
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(connection, state)

    gaps = [later - earlier for earlier, later in zip(beats, beats[1:], strict=False)]
    assert max(gaps) < 0.2  # a blocking provider on the loop would leave one ~0.3 s gap
    stop.set()
    await asyncio.wait_for(runner, 2)
    beat.cancel()


# --- D10 ----------------------------------------------------------------------------------------------------------


def test_device_report_says_whether_the_codex_seat_is_signed_in(state, monkeypatch):
    from octryx_claude import codex_seat

    monkeypatch.setattr(codex_seat, "reported_login", lambda root: root == state.root)
    assert device_runtime.device_report(state)["codex_seat_login"] is True
    monkeypatch.setattr(codex_seat, "reported_login", lambda root: False)
    assert device_runtime.device_report(state)["codex_seat_login"] is False


def test_device_report_carries_the_installed_build(state, monkeypatch):
    _enabled(state)
    monkeypatch.setattr(device_runtime, "installed_version", lambda: "0.2.0+d48159524a4c")
    assert device_runtime.device_report(state)["client_version"] == "0.2.0+d48159524a4c"
    monkeypatch.setattr(device_runtime, "installed_version", lambda: "")  # a checkout
    assert device_runtime.device_report(state)["client_version"] == device_runtime.__version__
