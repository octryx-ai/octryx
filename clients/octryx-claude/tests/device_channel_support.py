"""Shared fake connection, fake platform and handshake helpers for the device channel tests."""

from __future__ import annotations

import asyncio
import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from octryx_claude import device_state
from octryx_claude.device_channel import ChannelClient
from octryx_claude.device_channel_wire import ChannelClosedError

DEVICE_ID = "dev_0123456789abcdef"


class FakeConnection:
    def __init__(self) -> None:
        self.to_device: asyncio.Queue = asyncio.Queue()
        self.from_device: asyncio.Queue = asyncio.Queue()
        self.headers: dict[str, str] = {}

    async def send(self, text: str) -> None:
        await self.from_device.put(json.loads(text))

    async def recv(self) -> str:
        item = await self.to_device.get()
        if isinstance(item, ChannelClosedError):
            raise item
        return json.dumps(item)

    async def close(self) -> None:
        return None

    def push(self, message_type: str, body: dict | None = None) -> None:
        self.to_device.put_nowait({"v": 1, "type": message_type, "id": "x", "ts": 0, "body": body or {}})

    async def next(self) -> dict:
        return await asyncio.wait_for(self.from_device.get(), 2)


class FakePlatform:
    """Each connect attempt takes the next scripted outcome: a ChannelClosedError or a FakeConnection."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.urls: list[str] = []
        self.headers: list[dict] = []

    async def __call__(self, url: str, headers: dict) -> FakeConnection:
        self.urls.append(url)
        self.headers.append(headers)
        outcome = self.outcomes.pop(0) if self.outcomes else ChannelClosedError(1006, "unreachable")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _enabled(state) -> None:
    public = device_state.generate_key(state)
    device_state.save_device(state, {"device_id": DEVICE_ID, "name": "Box", "os": "linux",
                                     "base_url": "https://octryx.example.test", "folders": [], "paused": False,
                                     "max_parallel_jobs": 4, "public_key_for_test": public})


def _client(state, platform, *, tokens=None, sleeps=None, on_message=None, confirm_revoked=None):
    tokens = tokens if tokens is not None else []
    sleeps = sleeps if sleeps is not None else []

    def provider(force: bool) -> str:
        tokens.append(force)
        return f"channel-token-{len(tokens)}"

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await asyncio.sleep(0)

    return ChannelClient(state, token_provider=provider, report=lambda: {"folders": [], "paused": False},
                         on_message=on_message, connect=platform, sleep=sleep, jitter=lambda: 0.5,
                         confirm_revoked=confirm_revoked)


async def _handshake(connection: FakeConnection, state, *, streams=None, paused=False) -> dict:
    connection.push("challenge", {"nonce": "n-1"})
    hello = await connection.next()
    public = device_state.load_device(state)["public_key_for_test"]
    key = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(public + "="))
    key.verify(base64.urlsafe_b64decode(hello["body"]["signature"] + "=="),
               f"octryx-device-hello:v1:{DEVICE_ID}:n-1".encode())  # raises when the signature is wrong
    connection.push("welcome", {"device_id": DEVICE_ID, "paused": paused, "streams": streams or {}})
    return hello
