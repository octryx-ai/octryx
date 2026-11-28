from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from octryx_claude import device_renewal, device_state
from octryx_claude.device_channel import ChannelClient
from octryx_claude.device_channel_auth import channel_token
from octryx_claude.device_channel_wire import ChannelClosedError
from octryx_claude.state import CREDENTIAL_SET_DEVICE
from octryx_claude.tokens import TokenUnavailableError
from tests.device_channel_support import DEVICE_ID, FakeConnection, FakePlatform, _enabled, _handshake

BASE_URL = "https://octryx.example.test"


class FakeTokenPlatform:
    def __init__(self, state, *, renew_status: int = 200, renew_reason: str = "") -> None:
        self.public = device_state.load_device(state)["public_key_for_test"]
        self.renew_status = renew_status
        self.renew_reason = renew_reason
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            refresh = parse_qs(request.content.decode())["refresh_token"][0]
            self.calls.append(f"refresh:{refresh}")
            if refresh != "renewed-1":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "channel-renewed", "refresh_token": "renewed-2",
                                             "expires_in": 900, "scope": "device:connect"})
        assert request.url.path == device_renewal.RENEW_PATH
        body = json.loads(request.content)
        self.calls.append("renew")
        key = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(self.public + "="))
        key.verify(base64.urlsafe_b64decode(body["signature"] + "=="),
                   device_renewal.renewal_payload(DEVICE_ID, body["issued_at"]))  # raises on a wrong key
        if self.renew_status != 200:
            return httpx.Response(self.renew_status, json={"state": "unauthorized", "reason": self.renew_reason})
        return httpx.Response(200, json={"state": "renewed", "credential": {
            "refresh_token": "renewed-1", "client_id": "oec_test", "scopes": ["device:connect"]}})

    def factory(self):
        return lambda: httpx.Client(transport=httpx.MockTransport(self.handler))


def _device_credential(state) -> None:
    state.with_credential_set(CREDENTIAL_SET_DEVICE).write_credentials(
        {"base_url": BASE_URL, "client_id": "oec_test", "refresh_token": "lost-rotation", "scopes": [], "tokens": {}})


@pytest.mark.asyncio
async def test_token_expiry_with_a_refused_refresh_renews_with_the_key_and_reconnects(state):
    _enabled(state)
    _device_credential(state)
    platform_tokens = FakeTokenPlatform(state)
    first, second = FakeConnection(), FakeConnection()
    platform = FakePlatform(first, second)

    async def sleep(seconds: float) -> None:
        await asyncio.sleep(0)

    client = ChannelClient(state, token_provider=lambda force: channel_token(state, force,
                                                                             http_factory=platform_tokens.factory()),
                           report=lambda: {}, connect=platform, sleep=sleep, jitter=lambda: 0.5)
    # The first connection runs on a token that is still cached.
    creds = state.with_credential_set(CREDENTIAL_SET_DEVICE)
    cached = creds.credentials()
    cached["tokens"] = {"octryx-device": {"access_token": "channel-old", "expires_at": 4e9}}
    creds.write_credentials(cached)
    stop = asyncio.Event()
    runner = asyncio.create_task(client.run_forever(stop))
    await _handshake(first, state)
    assert platform.headers[0] == {"Authorization": "Bearer channel-old"}

    # The platform expires the token (the refresh that would have replaced it was lost): close 1000.
    cached = creds.credentials()
    cached["tokens"] = {}
    creds.write_credentials(cached)
    first.to_device.put_nowait(ChannelClosedError(1000, "device_token_expired"))
    await _handshake(second, state)

    assert platform.headers[1] == {"Authorization": "Bearer channel-renewed"}
    assert platform_tokens.calls == ["refresh:lost-rotation", "renew", "refresh:renewed-1"]
    assert creds.credentials()["refresh_token"] == "renewed-2"
    await asyncio.sleep(0.01)
    status = device_state.read_status(state)
    assert status["connected"] is True and not status.get("needs_login")
    stop.set()
    await asyncio.wait_for(runner, 2)


@pytest.mark.parametrize(("status", "reason", "code"), [
    (403, "device_revoked", "device_revoked"),
    (403, "device_signature_invalid", "renewal_rejected"),
    (401, "device_login_required", "renewal_rejected"),
    (401, "device_renewal_stale", "renewal_stale"),
])
def test_a_refused_renewal_is_a_fixed_code_and_keeps_the_credential(state, status, reason, code):
    _enabled(state)
    _device_credential(state)
    platform_tokens = FakeTokenPlatform(state, renew_status=status, renew_reason=reason)

    with pytest.raises(TokenUnavailableError) as raised:
        channel_token(state, False, http_factory=platform_tokens.factory())

    assert raised.value.code == code
    assert state.with_credential_set(CREDENTIAL_SET_DEVICE).credentials()["refresh_token"] == "lost-rotation"


@pytest.mark.asyncio
async def test_a_revoked_renewal_marks_the_device_revoked_and_a_rejected_one_needs_login(state):
    _enabled(state)

    async def sleep(seconds: float) -> None:
        await asyncio.sleep(0)

    for code, expected in (("renewal_rejected", "needs_login"), ("device_revoked", "revoked")):
        def provider(force: bool, code: str = code) -> str:
            raise TokenUnavailableError(code)

        client = ChannelClient(state, token_provider=provider, report=dict, connect=FakePlatform(), sleep=sleep,
                               confirm_revoked=lambda: "revoked")  # the platform confirms the revocation
        stop = asyncio.Event()
        runner = asyncio.create_task(client.run_forever(stop))
        for _ in range(20):
            await asyncio.sleep(0)
        assert client.idle_reason == expected
        stop.set()
        await asyncio.wait_for(runner, 2)
    assert device_state.load_device(state)["revoked"] is True


def test_a_revoked_mark_persisted_during_a_successful_renewal_is_cleared_by_it(state):
    _enabled(state)
    _device_credential(state)
    platform_tokens = FakeTokenPlatform(state)
    original = platform_tokens.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == device_renewal.RENEW_PATH:
            device = device_state.load_device(state)
            device["revoked"] = True  # the concurrent confirmation's persisted verdict
            device_state.save_device(state, device)
        return original(request)

    platform_tokens.handler = handler
    assert channel_token(state, False, http_factory=platform_tokens.factory()) == "channel-renewed"
    device = device_state.load_device(state)
    assert not device.get("revoked") and device_state.registered(device)


def test_a_revoked_answer_keeps_the_device_revoked(state):
    _enabled(state)
    _device_credential(state)
    platform_tokens = FakeTokenPlatform(state, renew_status=403, renew_reason="device_revoked")

    assert device_renewal.confirm_revocation(state, http=platform_tokens.factory()()) == device_renewal.VERDICT_REVOKED
    assert not device_state.load_device(state).get("revoked")  # only the channel persists it, after this verdict


def test_renewals_in_one_service_never_overlap(state):
    import threading

    _enabled(state)
    _device_credential(state)
    platform_tokens = FakeTokenPlatform(state)
    original = platform_tokens.handler
    active = {"now": 0, "max": 0}
    gate = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == device_renewal.RENEW_PATH:
            with gate:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            import time
            time.sleep(0.05)
            with gate:
                active["now"] -= 1
        return original(request)

    platform_tokens.handler = handler
    threads = [threading.Thread(target=lambda: device_renewal.renew_credential(
        state, http=platform_tokens.factory()())) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert active["max"] == 1
