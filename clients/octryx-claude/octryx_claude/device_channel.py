"""The device's outbound WSS channel to the platform: connect, prove the key, replay, stay connected.
A revoke is only a signal; ``revoked`` is persisted only when the key-signed renewal confirms it."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from . import device_state
from .device_channel_session import ChannelSession
from .device_channel_waits import ChannelWaits
from .device_channel_wire import (
    BACKOFF_MAX,
    BACKOFF_START,
    CLOSE_FORBIDDEN,
    CLOSE_REVOKED,
    CLOSE_UNAUTHORIZED,
    CREDENTIAL_REFUSALS,
    FAST_RETRY_SECONDS,
    FAST_RETRY_WINDOW_SECONDS,
    LOG_EVERY_SECONDS,
    NEEDS_LOGIN_CODES,
    RESTART_CLOSE_CODES,
    REVOKED_CODE,
    REVOKED_RECHECK_SECONDS,
    REVOKED_RETRY_START,
    ChannelClosedError,
    Connect,
    Connection,
    RevocationCheck,
    TokenProvider,
    _envelope,
    websockets_connect,
)
from .device_outbox import Outbox
from .device_renewal import VERDICT_UNCONFIRMED
from .output_redact import redact_outputs
from .state import LocalState
from .tokens import TokenUnavailableError

logger = logging.getLogger("octryx_claude.device")


class ChannelClient(ChannelSession, ChannelWaits):
    def __init__(
        self,
        state: LocalState,
        *,
        token_provider: TokenProvider,
        report: Callable[[], dict[str, Any]],
        on_message: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        connect: Connect = websockets_connect,
        outbox: Outbox | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        confirm_revoked: RevocationCheck | None = None,
        recheck_revoked: RevocationCheck | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.state = state
        self.token_provider = token_provider
        self.report = report
        self.on_message = on_message
        self.connect = connect
        self.outbox = outbox or Outbox(state)
        self.sleep = sleep
        self.jitter = jitter
        # Without a check nothing confirms a revoke signal, so none is ever persisted.
        self.confirm_revoked = confirm_revoked or (lambda: VERDICT_UNCONFIRMED)
        # Asks the platform about a persisted ``revoked`` (ignoring the local flag); None: never re-asked.
        self.recheck_revoked = recheck_revoked
        self.clock = clock
        self._fast_until = float("-inf")
        self._logged: dict[str, float] = {}
        self._attempt = 0
        self._revoked_due = True  # a ``revoked`` found at start is asked about at once
        self._revoked_wait = REVOKED_RECHECK_SECONDS
        self._revoked_retry = REVOKED_RETRY_START
        self.platform_paused = False
        self.connected = False
        self.idle_reason = ""
        self._welcomed = False
        self._connection: Connection | None = None
        self._token = ""
        self._send_lock = asyncio.Lock()

    @property
    def paused(self) -> bool:
        return self.platform_paused or bool(device_state.load_device(self.state).get("paused"))

    async def send_job(self, job_id: str, message_type: str, body: dict[str, Any]) -> None:
        entry = self.outbox.append(job_id, message_type, redact_outputs(body))
        await self._send_entry(job_id, entry)

    async def send_message(self, message_type: str, body: dict[str, Any]) -> bool:
        connection = self._connection
        if connection is None or not self._welcomed:
            return False
        try:
            await self._send(connection, message_type, body)
        except (ChannelClosedError, OSError):
            return False
        return True

    async def _send_entry(self, stream: str, entry: dict[str, Any]) -> None:
        connection = self._connection
        if connection is None:
            return
        with contextlib.suppress(ChannelClosedError, OSError):
            async with self._send_lock:
                await connection.send(_envelope(entry["type"], entry["body"], stream=stream, seq=entry["seq"]))

    async def _send(self, connection: Connection, message_type: str, body: dict[str, Any]) -> None:
        async with self._send_lock:
            await connection.send(_envelope(message_type, body))

    def _status(self, **changes: Any) -> None:
        current = device_state.read_status(self.state)
        current.update(changes, updated_at=time.time())
        device_state.write_status(self.state, current)

    async def run_forever(self, stop: asyncio.Event) -> None:
        backoff = BACKOFF_START
        forced_refresh = False
        while not stop.is_set():
            try:
                device = device_state.load_device(self.state)
                if not device_state.registered(device):
                    if device.get("device_id") and device.get("revoked"):
                        await self._revoked(stop)
                    else:
                        await self._idle("not_enabled", stop)
                    continue
                try:
                    # Off the loop: HTTP (10 s), a renewal and the credential file lock must not freeze running turns.
                    self._token = await asyncio.to_thread(self.token_provider, forced_refresh)
                except TokenUnavailableError as exc:
                    backoff, forced_refresh = await self._token_refused(exc, backoff, forced_refresh, stop)
                    continue
                self._welcomed = False
                try:
                    await self._session(device, stop)
                    backoff = BACKOFF_START
                    forced_refresh = False
                except ChannelClosedError as exc:
                    backoff, forced_refresh = await self._closed(exc, backoff, forced_refresh, stop)
            except Exception as exc:  # noqa: BLE001 - nothing in a reconnect may end the device service
                # E.g. a TimeoutError in the handshake: it must neither leave run_forever nor end the service
                # without a log line.
                logger.exception("device channel attempt failed unexpectedly (%s); reconnecting",
                                 type(exc).__name__)
                self.connected = False
                self._connection = None
                forced_refresh = False
                await self._retry_later(f"unexpected {type(exc).__name__}", backoff, stop)
                backoff = min(backoff * 2, BACKOFF_MAX)

    async def _token_refused(self, exc: TokenUnavailableError, backoff: float, forced_refresh: bool,
                             stop: asyncio.Event) -> tuple[float, bool]:
        if exc.code == REVOKED_CODE:
            return await self._revoke_signal(backoff, stop), False
        if exc.code in NEEDS_LOGIN_CODES:
            await self._idle("needs_login", stop)
            return backoff, False
        await self._retry_later(exc.code, backoff, stop)
        return min(backoff * 2, BACKOFF_MAX), forced_refresh

    async def _closed(self, exc: ChannelClosedError, backoff: float, forced_refresh: bool,
                      stop: asyncio.Event) -> tuple[float, bool]:
        self.connected = False
        self._connection = None
        self._status(connected=False)
        if self._welcomed:
            forced_refresh = False  # a refresh that led to a session worked; a later 4401 is a new problem
        if exc.code == CLOSE_REVOKED or exc.reason in ("revoke", REVOKED_CODE):
            return await self._revoke_signal(backoff, stop), False
        if exc.code == CLOSE_UNAUTHORIZED or exc.reason in CREDENTIAL_REFUSALS:
            if forced_refresh:
                await self._idle("needs_login", stop)
                return backoff, False
            logger.info("device channel closed (%s %s); refreshing the device credential", exc.code,
                        exc.reason)
            return backoff, True  # refresh once; a second 4401 means the login is gone
        if exc.code == CLOSE_FORBIDDEN:
            await self._idle(exc.reason or "device_refused", stop)
            return backoff, forced_refresh
        if self._welcomed:
            backoff = BACKOFF_START  # it was connected: start over at 1 s
            if exc.code in RESTART_CLOSE_CODES:
                self._fast_until = self.clock() + FAST_RETRY_WINDOW_SECONDS
        await self._retry_later(f"closed {exc.code} {exc.reason}".strip(), backoff, stop)
        return min(backoff * 2, BACKOFF_MAX), False

    async def _wait(self, seconds: float, stop: asyncio.Event) -> None:
        sleeper = asyncio.ensure_future(self.sleep(seconds))
        stopper = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait({sleeper, stopper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (sleeper, stopper):
                task.cancel()

    def _delay(self, backoff: float) -> float:
        base = FAST_RETRY_SECONDS if self.clock() < self._fast_until else backoff
        return base * (0.5 + self.jitter())

    async def _retry_later(self, reason: str, backoff: float, stop: asyncio.Event) -> None:
        delay = self._delay(backoff)
        self._attempt += 1
        now = self.clock()
        if now - self._logged.get(reason, float("-inf")) >= LOG_EVERY_SECONDS:
            self._logged[reason] = now
            logger.info("device channel not connected (%s); attempt %d, retrying in %.1f s", reason, self._attempt,
                        delay)
        self._status(connected=False, last_error=reason, attempt=self._attempt, next_retry_at=time.time() + delay)
        await self._wait(delay, stop)


__all__ = [
    "ChannelClient",
]
