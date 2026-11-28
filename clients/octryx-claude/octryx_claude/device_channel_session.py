"""One connected device channel session: handshake, replay, receive, housekeeping (mixed into
``device_channel.ChannelClient``)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from . import device_state, local_profiles
from .device_channel_wire import (
    CLOSE_REVOKED,
    CLOSE_UNAUTHORIZED,
    LOCAL_SESSIONS_SECONDS,
    NEEDS_LOGIN_CODES,
    PROTOCOL_VERSION,
    REVOKED_CODE,
    STATE_CHECK_SECONDS,
    STATUS_HEARTBEAT_SECONDS,
    TOKEN_CHECK_SECONDS,
    ChannelClosedError,
    Connection,
    _envelope,
    _handshake_message,
    channel_url,
)
from .tokens import TokenUnavailableError

logger = logging.getLogger("octryx_claude.device")


class ChannelSession:
    async def _session(self, device: dict[str, Any], stop: asyncio.Event) -> None:
        url = channel_url(str(device.get("base_url") or ""))
        connection = await self.connect(url, {"Authorization": f"Bearer {self._token}"})
        try:
            challenge = await _handshake_message(connection)
            if challenge.get("type") != "challenge":
                raise ChannelClosedError(4400, "handshake_unexpected")
            nonce = str(challenge.get("body", {}).get("nonce") or "")
            payload = f"octryx-device-hello:v{PROTOCOL_VERSION}:{device['device_id']}:{nonce}".encode()
            hello = {"device_id": device["device_id"], "signature": device_state.sign(self.state, payload),
                     **self.report()}
            await connection.send(_envelope("hello", hello))
            welcome = await _handshake_message(connection)
            if welcome.get("type") != "welcome":
                raise ChannelClosedError(4400, "handshake_unexpected")
            body = welcome.get("body") or {}
            self.platform_paused = body.get("paused") is True
            self._connection = connection
            self.connected = True
            self._welcomed = True
            self._attempt = 0
            self._fast_until = float("-inf")
            self._status(connected=True, revoked=False, needs_login=False, connected_at=time.time(), last_error="",
                         attempt=0, next_retry_at=None)
            logger.info("device channel connected")
            streams = body.get("streams") if isinstance(body.get("streams"), dict) else {}
            await self._replay(streams)
            if self.on_message is not None:
                await self.on_message("connected", {"paused": self.platform_paused})
            await self._serve(connection, stop)
        finally:
            self._connection = None
            self.connected = False
            with contextlib.suppress(Exception):
                await connection.close()

    async def _replay(self, streams: dict[str, Any]) -> None:
        for stream in self.outbox.streams():
            stored = int(streams.get(stream) or 0)
            self.outbox.ack(stream, stored)
            for entry in self.outbox.pending(stream, stored):
                await self._send_entry(stream, entry)

    async def _serve(self, connection: Connection, stop: asyncio.Event) -> None:
        receiver = asyncio.ensure_future(self._receive(connection))
        stopper = asyncio.ensure_future(stop.wait())
        housekeeping = asyncio.ensure_future(self._housekeeping(connection))
        try:
            done, _ = await asyncio.wait({receiver, stopper, housekeeping}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stopper and task.exception() is not None:
                    raise task.exception()
        finally:
            for task in (receiver, stopper, housekeeping):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _receive(self, connection: Connection) -> None:
        while True:
            try:
                message = json.loads(await connection.recv())
            except ValueError:
                continue
            message_type = str(message.get("type") or "")
            body = message.get("body") if isinstance(message.get("body"), dict) else {}
            if message_type == "ack":
                self.outbox.ack(str(body.get("stream") or ""), int(body.get("seq") or 0))
            elif message_type == "nack":
                stream, expected = str(body.get("stream") or ""), int(body.get("expected") or 1)
                for entry in self.outbox.pending(stream, expected - 1):
                    await self._send_entry(stream, entry)
            elif message_type == "revoke":
                raise ChannelClosedError(CLOSE_REVOKED, "revoke")
            elif message_type in ("pause", "resume"):
                self.platform_paused = message_type == "pause"
                if self.on_message is not None:
                    await self.on_message(message_type, body)
            elif message_type != "pong" and self.on_message is not None:
                await self.on_message(message_type, body)

    async def _report_local_sessions(self, connection: Connection, last: str) -> str:
        try:
            local = await asyncio.to_thread(local_profiles.report, self.state)
        except Exception:  # noqa: BLE001 - a scan problem never ends the channel
            logger.warning("local session scan failed", exc_info=True)
            return last
        text = json.dumps(local, sort_keys=True)
        if text != last and (local["profiles"] or last):
            await self._send(connection, "local_sessions", local)
            return text
        return last

    async def _housekeeping(self, connection: Connection) -> None:
        last_report = json.dumps(self.report(), sort_keys=True)
        last_local = ""
        rounds = 0
        while True:
            if rounds % int(LOCAL_SESSIONS_SECONDS // STATE_CHECK_SECONDS) == 0:
                last_local = await self._report_local_sessions(connection, last_local)
            await self.sleep(STATE_CHECK_SECONDS)
            rounds += 1
            if rounds % int(STATUS_HEARTBEAT_SECONDS // STATE_CHECK_SECONDS) == 0:
                self._status(connected=True)  # a heartbeat: ``device status`` tells a stale file from a live one
            report = json.dumps(self.report(), sort_keys=True)
            if report != last_report:
                last_report = report
                await self._send(connection, "state", json.loads(report))
            if rounds % int(TOKEN_CHECK_SECONDS // STATE_CHECK_SECONDS) == 0:
                try:
                    token = await asyncio.to_thread(self.token_provider, False)  # may renew over HTTP
                except TokenUnavailableError as exc:
                    # Do not wait for the platform to expire the token: a revoked device or a refused renewal
                    # ends the session now; anything else (unreachable) is retried on the next round.
                    if exc.code == REVOKED_CODE:
                        raise ChannelClosedError(CLOSE_REVOKED, "revoke") from exc
                    if exc.code in NEEDS_LOGIN_CODES:
                        raise ChannelClosedError(CLOSE_UNAUTHORIZED, exc.code) from exc
                    logger.info("device token refresh failed (%s); retrying before it expires", exc.code)
                    continue
                if token != self._token:
                    self._token = token
                    await self._send(connection, "token", {"access_token": token})
