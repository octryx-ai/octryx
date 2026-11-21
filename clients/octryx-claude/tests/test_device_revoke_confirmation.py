"""A revoke signal is persisted only when the platform confirms it.

A refused grant refresh and a channel close 4410 ``revoke`` can happen without a revoke on the platform (e.g. a
replayed rotation during a redeploy). The client asks the key-signed renewal first: only its ``device_revoked``
revokes; a real revoke stays effective.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from octryx_claude import device_renewal, device_state
from octryx_claude.device_channel import ChannelClient
from octryx_claude.device_channel_auth import revocation_check
from octryx_claude.device_channel_wire import ChannelClosedError
from octryx_claude.state import CREDENTIAL_SET_DEVICE
from octryx_claude.tokens import TokenUnavailableError
from tests.device_channel_support import FakeConnection, FakePlatform, _client, _enabled, _handshake
from tests.test_device_renewal import FakeTokenPlatform, _device_credential


async def _settle(rounds: int = 40) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_a_redeploy_revoke_close_with_an_active_device_reconnects_and_never_persists_revoked(state):
    _enabled(state)
    first, second = FakeConnection(), FakeConnection()
    platform = FakePlatform(first, second)
    asked: list[str] = []
    client = _client(state, platform, confirm_revoked=lambda: asked.append("check") or "active")
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(first, state)

    first.to_device.put_nowait(ChannelClosedError(4410, "revoke"))  # the recheck after the grant ended
    await _handshake(second, state)

    assert asked == ["check"]
    assert not device_state.load_device(state).get("revoked")
    assert device_state.registered(device_state.load_device(state))
    assert len(platform.urls) == 2
    await _settle()
    assert device_state.read_status(state)["connected"] is True
    assert not device_state.read_status(state).get("revoked")
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_an_unconfirmed_revoke_backs_off_and_keeps_the_device_enabled(state):
    _enabled(state)
    sleeps: list[float] = []
    second = FakeConnection()
    platform = FakePlatform(ChannelClosedError(4410, "revoke"), second)
    client = _client(state, platform, sleeps=sleeps, confirm_revoked=lambda: "unconfirmed")
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    await _handshake(second, state)

    assert not device_state.load_device(state).get("revoked")
    assert sleeps == [1.0]  # one backoff (jitter 0.5 → 1.0×), then the next connect
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_without_a_revocation_check_no_revoke_signal_is_ever_persisted(state):
    _enabled(state)
    connection = FakeConnection()
    client = _client(state, FakePlatform(ChannelClosedError(4410, "revoke"), connection))
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    await _handshake(connection, state)

    assert not device_state.load_device(state).get("revoked")
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_a_device_revoked_token_answer_is_confirmed_before_it_revokes(state):
    _enabled(state)
    answers = iter([TokenUnavailableError("device_revoked")])
    connection = FakeConnection()

    def provider(force: bool) -> str:
        error = next(answers, None)
        if error is not None:
            raise error
        return "channel-renewed"

    async def sleep(seconds: float) -> None:
        await asyncio.sleep(0)

    client = ChannelClient(state, token_provider=provider, report=dict, connect=FakePlatform(connection),
                           sleep=sleep, confirm_revoked=lambda: "active")
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))

    await _handshake(connection, state)

    assert not device_state.load_device(state).get("revoked")
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_a_refused_confirmation_needs_login_not_a_revocation(state):
    _enabled(state)
    client = _client(state, FakePlatform(ChannelClosedError(4410, "revoke")), confirm_revoked=lambda: "needs_login")
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _settle()

    assert client.idle_reason == "needs_login"
    assert not device_state.load_device(state).get("revoked")
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.parametrize(("status", "reason", "verdict"), [
    (200, "", "active"),
    (403, "device_revoked", "revoked"),
    (403, "device_signature_invalid", "needs_login"),
    (401, "device_login_required", "needs_login"),
    (401, "device_renewal_stale", "unconfirmed"),
    (502, "", "unconfirmed"),
    (503, "", "unconfirmed"),
])
def test_the_platforms_key_signed_renewal_is_the_authority(state, status, reason, verdict):
    _enabled(state)
    _device_credential(state)
    platform_tokens = FakeTokenPlatform(state, renew_status=status, renew_reason=reason)

    assert revocation_check(state, http_factory=platform_tokens.factory()) == verdict
    assert platform_tokens.calls == ["renew"]
    refresh = state.with_credential_set(CREDENTIAL_SET_DEVICE).credentials()["refresh_token"]
    assert refresh == ("renewed-1" if verdict == "active" else "lost-rotation")


def test_an_unreachable_platform_never_confirms_a_revocation(state):
    _enabled(state)
    _device_credential(state)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with httpx.Client(transport=httpx.MockTransport(unreachable)) as http:
        assert device_renewal.confirm_revocation(state, http=http) == "unconfirmed"
    assert not device_state.load_device(state).get("revoked")
