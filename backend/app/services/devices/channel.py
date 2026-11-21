"""The device channel: one outbound WebSocket per device, authenticated and sequenced.

Handshake (every step has a deadline; any failure closes with a fixed code):

1. The device connects with its 15-minute channel token (``Authorization: Bearer``; audience
   ``octryx-device``, scope ``device:connect``, a device grant of an active device).
2. The platform sends ``challenge {nonce}``.
3. The device answers ``hello {device_id, signature, folders, profiles_available, max_parallel_jobs, paused,
   seat_login, codex_seat_login, client_version, service_kind}``; the signature is Ed25519 over :func:`hello_payload`
   with the key registered for the device, so a copied token alone cannot impersonate it.
4. The platform stores the device's own report, attaches the connection to the hub and answers ``welcome``
   with the platform pause and the last acknowledged ``seq`` per stream, so the device replays only what the
   platform has not stored.

Then:

- every message is ``{v, type, id, stream?, seq?, ts, body}``. A message with ``stream`` and ``seq`` is a
  sequenced device event: it is stored exactly once in order and answered ``ack {stream, seq}``; an
  already-stored ``seq`` is acknowledged again (a replay), a gap is answered ``nack {stream, expected}``
  and the device replays from there. Nothing is lost or stored twice across reconnects.
- ``token {access_token}`` replaces the channel token before it expires, without a reconnect; a token that
  expires unreplaced, a revoked device or grant (checked every ``RECHECK_SECONDS``) closes the channel. Only a
  revoked *device* closes as ``revoke`` (4410); a grant or token refusal (a refresh replay, the grant's end)
  closes 1000 with its reason, so the device refreshes or renews its credential instead of treating it as a
  revocation.
- the tick (offers, cancels, ``last_seen_at``, token and revocation checks) survives a failing round (a database
  hiccup): it logs, backs off and goes on; after ``TICK_FAILURES_MAX`` failures in a row, or should the tick task
  end on its own, the channel closes 1011 so the device reconnects. A connection whose tick has not succeeded
  for ``STALE_AFTER_SECONDS`` is not counted as connected (``hub``).
- ``state {...}`` updates the device's report (folders, paused, limits).
- the platform side pushes ``pause``, ``resume`` and ``revoke`` through the hub; the job layer
  (``ChannelHandlers``) delivers offers, approval decisions and cancels from the database on every tick
  (≤ 1 s; the database is the bus between replicas).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import Callable
from typing import Any

from ...models import AuditLog, UserDevice
from ...time_utils import utc_now
from .channel_protocol import (
    CLOSE_FORBIDDEN,
    CLOSE_PROTOCOL,
    CLOSE_UNAUTHORIZED,
    REASON_CHANNEL_ERROR,
    REASON_HANDSHAKE_TIMEOUT,
    REASON_HELLO_INVALID,
    REASON_REPLACED,
    REASON_SIGNATURE_INVALID,
    REASON_TOKEN_EXPIRED,
    RESULT_DUPLICATE,
    RESULT_STORED,
    ChannelHandlers,
    ChannelSocket,
    DeviceChannelConnection,
    SessionFactory,
    _close_reason,
    _token_expiry,
    apply_reported_state,
    channel_handlers,
    envelope,
    hello_payload,
    reported_tools,
    verify_signature,
)
from .credential import DeviceCredential, resolve_device_credential
from .hub import device_hub
from .registry import report_device_state

logger = logging.getLogger(__name__)

HANDSHAKE_SECONDS = 15.0
RECHECK_SECONDS = 30.0
TICK_SECONDS = 1.0
LAST_SEEN_SECONDS = 30.0
# A failing tick backs off 1, 2, 4, 8, 8 … s; this many failures in a row (~45 s) close the channel.
TICK_FAILURES_MAX = 8
TICK_BACKOFF_MAX_SECONDS = 8.0


class DeviceChannelSession:
    def __init__(self, socket: ChannelSocket, *, token: str, session_factory: SessionFactory,
                 handlers: ChannelHandlers | None = None, clock: Callable[[], float] = time.time) -> None:
        self.socket = socket
        self.token = token
        self.session_factory = session_factory
        self.handlers = handlers or channel_handlers()
        self.clock = clock
        self.connection: DeviceChannelConnection | None = None
        self._last_recheck = self._last_seen = 0.0

    async def _credential(self, token: str) -> DeviceCredential | str:
        async with self.session_factory() as db:
            return await resolve_device_credential(db, token)

    async def _refuse(self, code: int, reason: str) -> None:
        with contextlib.suppress(Exception):
            await self.socket.close(code=code, reason=reason)

    async def _handshake(self) -> DeviceChannelConnection | None:
        credential = await self._credential(self.token)
        if isinstance(credential, str):
            await self._refuse(CLOSE_UNAUTHORIZED, credential)
            return None
        nonce = secrets.token_urlsafe(24)
        await self.socket.send_json(envelope("challenge", {"nonce": nonce}))
        try:
            hello = await asyncio.wait_for(self.socket.receive_json(), HANDSHAKE_SECONDS)
        except TimeoutError:
            await self._refuse(CLOSE_PROTOCOL, REASON_HANDSHAKE_TIMEOUT)
            return None
        body = hello.get("body") if isinstance(hello, dict) and hello.get("type") == "hello" else None
        if not isinstance(body, dict) or body.get("device_id") != credential.device.id:
            await self._refuse(CLOSE_PROTOCOL, REASON_HELLO_INVALID)
            return None
        if not verify_signature(credential.device.public_key, hello_payload(credential.device.id, nonce),
                                str(body.get("signature") or "")):
            await self._refuse(CLOSE_FORBIDDEN, REASON_SIGNATURE_INVALID)
            return None
        async with self.session_factory() as db:
            device = await db.get(UserDevice, credential.device.id)
            await report_device_state(db, device, body)
            streams = await self.handlers.welcome_streams(db, device)
            db.add(AuditLog(user_id=credential.user_id, action="device.channel.connected", resource_type="user_device",
                            resource_id=device.id, details={"client_version": device.client_version}))
            await db.commit()
            paused = bool(device.paused)
        connection = DeviceChannelConnection(self.socket, device, user_id=credential.user_id,
                                             token_expires_at=_token_expiry(self.token))
        connection.seat_login = body.get("seat_login") is True
        connection.codex_seat_login = body.get("codex_seat_login") is True
        connection.tools = reported_tools(body.get("tools"))
        previous = await device_hub.attach(connection)
        if previous is not None and previous is not connection:
            await previous.close(REASON_REPLACED)
        await connection.send("welcome", {"device_id": device.id, "paused": paused, "streams": streams})
        logger.info("device_channel.connected device=%s", device.id)
        return connection

    async def run(self) -> None:
        connection = await self._handshake()
        if connection is None:
            return
        self.connection = connection
        ticker = asyncio.create_task(self._tick_loop(connection))
        receiver = asyncio.create_task(self._receive_loop(connection))
        try:
            done, _pending = await asyncio.wait({ticker, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if ticker in done and not connection.closed.is_set():
                # The tick ended without closing: no offers, cancels or checks would reach this device any more.
                error = None if ticker.cancelled() else ticker.exception()
                logger.error("device_channel.tick_ended device=%s error=%s", connection.device_id,
                             type(error).__name__ if error else "none")
                await connection.close(REASON_CHANNEL_ERROR)
            await receiver
        finally:
            for task in (ticker, receiver):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            connection.closed.set()
            await device_hub.detach(connection)
            async with self.session_factory() as db:
                await self.handlers.disconnected(db, connection.device_id)
                db.add(AuditLog(user_id=connection.owner_user_id, action="device.channel.disconnected",
                                resource_type="user_device", resource_id=connection.device_id,
                                details={"reason": connection.close_reason or "closed"}))
                await db.commit()
            logger.info("device_channel.disconnected device=%s reason=%s", connection.device_id,
                        connection.close_reason or "closed")

    async def _receive_loop(self, connection: DeviceChannelConnection) -> None:
        receive = asyncio.ensure_future(self.socket.receive_json())
        closed = asyncio.ensure_future(connection.closed.wait())
        try:
            while True:
                done, _pending = await asyncio.wait({receive, closed}, return_when=asyncio.FIRST_COMPLETED)
                if closed in done:
                    return
                try:
                    message = receive.result()
                except Exception:  # noqa: BLE001 - a disconnect or an unreadable frame ends the channel
                    return
                if isinstance(message, dict):
                    await self._dispatch(connection, message)
                receive = asyncio.ensure_future(self.socket.receive_json())
        finally:
            for task in (receive, closed):
                task.cancel()

    async def _dispatch(self, connection: DeviceChannelConnection, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")
        body = message.get("body") if isinstance(message.get("body"), dict) else {}
        if message_type == "token":
            await self._replace_token(connection, str(body.get("access_token") or ""))
            return
        if message_type in ("ping", "heartbeat"):
            await connection.send("pong", {})
            return
        async with self.session_factory() as db:
            if message_type == "state":
                device = await db.get(UserDevice, connection.device_id)
                if device is not None:
                    await report_device_state(db, device, body)
                apply_reported_state(connection, body)
            elif message.get("stream") and isinstance(message.get("seq"), int):
                result = await self.handlers.stream_event(db, connection, message)
                await db.commit()
                if result in (RESULT_STORED, RESULT_DUPLICATE):
                    await connection.send("ack", {"stream": message["stream"], "seq": message["seq"]})
                else:
                    await connection.send("nack", {"stream": message["stream"], "expected": int(result)})
                return
            else:
                await self.handlers.message(db, connection, message)
            await db.commit()

    async def _replace_token(self, connection: DeviceChannelConnection, token: str) -> None:
        credential = await self._credential(token)
        if isinstance(credential, str):
            await connection.close(_close_reason(credential))
            return
        if credential.device.id != connection.device_id:
            await connection.close(REASON_TOKEN_EXPIRED)
            return
        self.token = token
        connection.token_expires_at = _token_expiry(token)

    async def _tick_loop(self, connection: DeviceChannelConnection) -> None:
        self._last_recheck = self._last_seen = self.clock()
        failures = 0
        while not connection.closed.is_set():
            await asyncio.sleep(min(TICK_SECONDS * 2 ** failures, TICK_BACKOFF_MAX_SECONDS) if failures
                                else TICK_SECONDS)
            try:
                if not await self._tick(connection):
                    return
            except Exception as exc:  # noqa: BLE001 - one failing round (a database hiccup) never ends the ticker
                failures += 1
                logger.warning("device_channel.tick_failed device=%s failures=%d error=%s", connection.device_id,
                               failures, type(exc).__name__, exc_info=failures == 1)
                if failures >= TICK_FAILURES_MAX:
                    logger.error("device_channel.tick_gave_up device=%s", connection.device_id)
                    await connection.close(REASON_CHANNEL_ERROR)
                    return
                continue
            if failures:
                logger.info("device_channel.tick_recovered device=%s after=%d", connection.device_id, failures)
            failures = 0
            connection.last_tick_at = time.monotonic()

    async def _tick(self, connection: DeviceChannelConnection) -> bool:
        """One round; ``False`` when it closed the channel. A failed check is retried on the next round."""
        now = self.clock()
        if connection.token_expires_at and now >= connection.token_expires_at:
            await connection.close(REASON_TOKEN_EXPIRED)
            return False
        if now - self._last_recheck >= RECHECK_SECONDS:
            credential = await self._credential(self.token)
            self._last_recheck = now
            if isinstance(credential, str):
                await connection.close(_close_reason(credential))
                return False
        async with self.session_factory() as db:
            if now - self._last_seen >= LAST_SEEN_SECONDS:
                device = await db.get(UserDevice, connection.device_id)
                if device is not None:
                    device.last_seen_at = utc_now()
            await self.handlers.tick(db, connection)
            await db.commit()
        if now - self._last_seen >= LAST_SEEN_SECONDS:
            self._last_seen = now
        return True


__all__ = [
    "DeviceChannelSession",
]
