"""The device channel's wire format and one live connection: message envelope, hello signature, close codes,
reasons, the job layer's handler hooks and their registration (``devices.channel``)."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import UserDevice

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 256 * 1024

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_PROTOCOL = 4400
CLOSE_REPLACED = 4409
CLOSE_REVOKED = 4410
CLOSE_INTERNAL = 1011

REASON_HANDSHAKE_TIMEOUT = "handshake_timeout"
REASON_HELLO_INVALID = "hello_invalid"
REASON_SIGNATURE_INVALID = "device_signature_invalid"
REASON_TOKEN_EXPIRED = "device_token_expired"
REASON_REPLACED = "device_connection_replaced"
REASON_REVOKED = "device_revoked"
REASON_CHANNEL_ERROR = "device_channel_error"

RESULT_STORED = "stored"
RESULT_DUPLICATE = "duplicate"


def reported_tools(value: Any) -> dict[str, str | None]:
    """The device's ``tools`` ``{id: version | None}`` (the launcher brings its pinned tools),
    bounded; anything else dropped. A tool reported ``None`` is not available on that device."""
    if not isinstance(value, dict):
        return {}
    return {str(key)[:40]: (str(version)[:40] if isinstance(version, str) and version else None)
            for key, version in list(value.items())[:40] if isinstance(key, str) and key}


def hello_payload(device_id: str, nonce: str) -> bytes:
    return f"octryx-device-hello:v{PROTOCOL_VERSION}:{device_id}:{nonce}".encode()


def verify_signature(public_key: str, payload: bytes, signature: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4)))
        key.verify(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)), payload)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def envelope(message_type: str, body: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": message_type, "id": uuid.uuid4().hex, "ts": time.time(),
            "body": body or {}, **extra}


class ChannelSocket(Protocol):
    async def receive_json(self) -> Any: ...

    async def send_json(self, data: Any) -> None: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


class ChannelHandlers:
    """The job layer's hooks into the channel (``services/devices/jobs_channel``). The base class does nothing."""

    async def welcome_streams(self, db: AsyncSession, device: UserDevice) -> dict[str, int]:
        """The last stored ``seq`` per stream (job) still open on this device."""
        return {}

    async def stream_event(self, db: AsyncSession, connection: DeviceChannelConnection,
                           message: dict[str, Any]) -> str | int:
        """Store one sequenced event: ``stored``, ``duplicate`` or the expected ``seq`` (a gap)."""
        return RESULT_STORED

    async def message(self, db: AsyncSession, connection: DeviceChannelConnection, message: dict[str, Any]) -> None:
        """An unsequenced device message (``job_accepted``, ``job_rejected``, …)."""

    async def tick(self, db: AsyncSession, connection: DeviceChannelConnection) -> None:
        """Deliver what the database holds for this device (offers, decisions, cancels)."""

    async def disconnected(self, db: AsyncSession, device_id: str) -> None:
        """The device went away (the offline grace starts)."""


class DeviceChannelConnection:
    """One live device socket; ``send`` is safe from any task (the hub, the tick, the receive loop)."""

    def __init__(self, socket: ChannelSocket, device: UserDevice, *, user_id: str, token_expires_at: float) -> None:
        self.socket = socket
        self.device_id = device.id
        self.owner_user_id = user_id
        self.seat_login = False
        self.codex_seat_login = False  # the Codex seat's ChatGPT login (yes/no only), as the device reports it
        self.tools: dict[str, str | None] = {}  # the launcher's pinned tools {id: version | None} (reported_tools)
        self.token_expires_at = token_expires_at
        self.closed = asyncio.Event()
        self.close_reason = ""
        self.last_tick_at = time.monotonic()  # the last successful tick (``healthy``)
        self._send_lock = asyncio.Lock()

    def healthy(self) -> bool:
        """Open and ticking: a connection whose tick keeps failing is not a device the platform can reach."""
        return not self.closed.is_set() and time.monotonic() - self.last_tick_at < STALE_AFTER_SECONDS

    async def send(self, message_type: str, body: dict[str, Any], **extra: Any) -> None:
        if self.closed.is_set():
            return
        async with self._send_lock:
            await self.socket.send_json(envelope(message_type, body, **extra))

    async def close(self, reason: str) -> None:
        if self.closed.is_set():
            return
        self.close_reason = reason
        if reason == "revoke":
            with contextlib.suppress(Exception):
                await self.send("revoke", {})
        self.closed.set()
        code = _CLOSE_CODES.get(reason, 1000)
        with contextlib.suppress(Exception):
            await self.socket.close(code=code, reason=reason)


def apply_reported_state(connection: DeviceChannelConnection, body: dict[str, Any]) -> None:
    """A ``state`` message's live report on the connection: only the keys the device sent change."""
    if "seat_login" in body:
        connection.seat_login = body["seat_login"] is True
    if "codex_seat_login" in body:
        connection.codex_seat_login = body["codex_seat_login"] is True
    if "tools" in body:
        connection.tools = reported_tools(body["tools"])


STALE_AFTER_SECONDS = 90.0
_CLOSE_CODES = {"revoke": CLOSE_REVOKED, REASON_REPLACED: CLOSE_REPLACED, REASON_CHANNEL_ERROR: CLOSE_INTERNAL}


def _close_reason(refusal: str) -> str:
    """How a credential refusal ends a live channel: only a revoked device is a ``revoke``."""
    return "revoke" if refusal == REASON_REVOKED else refusal


SessionFactory = Callable[[], Any]


def _token_expiry(token: str) -> float:
    import jwt

    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception:  # noqa: BLE001 - the token was verified already; an unreadable exp means "now"
        return 0.0
    return float(claims.get("exp") or 0)


_handlers: ChannelHandlers | None = None


def channel_handlers() -> ChannelHandlers:
    """The job layer's handlers once registered (``jobs_channel``), else the no-op base."""
    return _handlers or ChannelHandlers()


def register_channel_handlers(handlers: ChannelHandlers) -> None:
    global _handlers
    _handlers = handlers


