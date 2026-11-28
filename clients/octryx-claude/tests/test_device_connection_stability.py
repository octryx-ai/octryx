from __future__ import annotations

import asyncio

import pytest

from octryx_claude import device_state
from octryx_claude.device_channel_auth import revocation_check
from octryx_claude.device_channel_wire import REVOKED_RECHECK_SECONDS, ChannelClosedError
from octryx_claude.state import CREDENTIAL_SET_DEVICE
from tests.device_channel_support import FakeConnection, FakePlatform, _client, _enabled, _handshake
from tests.device_connection_stability_support import _revoked_locally, _until
from tests.test_device_renewal import FakeTokenPlatform, _device_credential


@pytest.mark.asyncio
async def test_revoked_flag_is_reverified_on_start_and_cleared_when_the_platform_says_active(state):
    _enabled(state)
    _revoked_locally(state)  # a false positive (a race, a restore, a hand edit)
    connection = FakeConnection()
    asked: list[str] = []
    client = _client(state, FakePlatform(connection))
    client.recheck_revoked = lambda: asked.append("recheck") or "active"
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    await _handshake(connection, state)

    assert asked == ["recheck"]
    assert not device_state.load_device(state).get("revoked")
    await _until(lambda: device_state.read_status(state).get("connected") is True)
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_revoked_flag_is_reverified_periodically_and_kept_only_on_an_authoritative_answer(state):
    _enabled(state)
    _revoked_locally(state)
    connection = FakeConnection()
    answers = iter(["unconfirmed", "revoked", "active"])
    asked: list[str] = []
    sleeps: list[float] = []
    client = _client(state, FakePlatform(connection), sleeps=sleeps)

    def recheck() -> str:
        verdict = next(answers)
        asked.append(verdict)
        assert device_state.load_device(state).get("revoked") is True  # kept until the platform says otherwise
        return verdict

    client.recheck_revoked = recheck
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    await _handshake(connection, state)

    assert asked == ["unconfirmed", "revoked", "active"]
    idle = [value for value in sleeps if value != 5.0]  # 5.0: the connected state-check timer
    # No answer: retried after a minute; a confirmed revocation: asked again after REVOKED_RECHECK_SECONDS.
    assert sum(idle[:1]) == 60.0
    assert sum(idle[1:]) == REVOKED_RECHECK_SECONDS
    assert not device_state.load_device(state).get("revoked")
    stop.set()
    await asyncio.wait_for(runner, 2)


def test_the_recheck_asks_the_platform_although_revoked_is_persisted(state):
    _enabled(state)
    _device_credential(state)
    _revoked_locally(state)
    platform_tokens = FakeTokenPlatform(state)

    # The ordinary confirmation never asks for a device already marked revoked …
    assert revocation_check(state, http_factory=platform_tokens.factory()) == "revoked"
    assert platform_tokens.calls == []
    # … the recheck does, and an active answer clears the flag.
    assert revocation_check(state, http_factory=platform_tokens.factory(), recheck=True) == "active"
    assert platform_tokens.calls == ["renew"]
    assert not device_state.load_device(state).get("revoked")
    assert state.with_credential_set(CREDENTIAL_SET_DEVICE).credentials()["refresh_token"] == "renewed-1"


def test_a_recheck_answered_device_revoked_keeps_the_flag(state):
    _enabled(state)
    _device_credential(state)
    _revoked_locally(state)
    platform_tokens = FakeTokenPlatform(state, renew_status=403, renew_reason="device_revoked")

    assert revocation_check(state, http_factory=platform_tokens.factory(), recheck=True) == "revoked"
    assert device_state.load_device(state)["revoked"] is True


@pytest.mark.asyncio
async def test_a_grant_refusal_close_refreshes_once_and_never_asks_about_a_revocation(state):
    _enabled(state)
    first, second = FakeConnection(), FakeConnection()
    tokens: list[bool] = []
    sleeps: list[float] = []
    asked: list[str] = []
    client = _client(state, FakePlatform(first, second), tokens=tokens, sleeps=sleeps,
                     confirm_revoked=lambda: asked.append("check") or "active")
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(first, state)

    first.to_device.put_nowait(ChannelClosedError(1000, "device_grant_revoked"))  # the platform's recheck
    await _handshake(second, state)

    assert tokens == [False, True]  # one forced refresh (the provider renews with the key when refused)
    assert asked == []
    assert not device_state.load_device(state).get("revoked")
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_a_4401_after_a_session_that_a_forced_refresh_opened_refreshes_again_not_needs_login(state):
    _enabled(state)
    second, third = FakeConnection(), FakeConnection()
    platform = FakePlatform(ChannelClosedError(4401, "device_token_invalid"), second, third)
    tokens: list[bool] = []
    client = _client(state, platform, tokens=tokens)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(second, state)  # opened by the forced refresh

    second.to_device.put_nowait(ChannelClosedError(4401, "device_grant_revoked"))
    await _handshake(third, state)

    assert tokens == [False, True, True]
    assert client.idle_reason == ""
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_a_4401_device_revoked_is_a_revoke_signal(state):
    _enabled(state)
    asked: list[str] = []
    client = _client(state, FakePlatform(ChannelClosedError(4401, "device_revoked")),
                     confirm_revoked=lambda: asked.append("check") or "revoked")
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    await _until(lambda: client.idle_reason == "revoked")

    assert asked == ["check"]
    assert device_state.load_device(state)["revoked"] is True
    stop.set()
    await asyncio.wait_for(runner, 2)
