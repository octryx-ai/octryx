"""The device channel's waiting states: a revoke signal, a persisted ``revoked`` and the idle wait for a changed
device or credential file (mixed into ``device_channel.ChannelClient``)."""

from __future__ import annotations

import asyncio
import logging

from . import device_state
from .device_channel_wire import (
    BACKOFF_MAX,
    BACKOFF_START,
    IDLE_CHECK_SECONDS,
    NEEDS_LOGIN_RETRY_SECONDS,
    REVOKED_RECHECK_MAX_SECONDS,
    REVOKED_RECHECK_SECONDS,
    REVOKED_RETRY_START,
)
from .device_renewal import VERDICT_ACTIVE, VERDICT_NEEDS_LOGIN, VERDICT_REVOKED

logger = logging.getLogger("octryx_claude.device")


class ChannelWaits:
    async def _revoke_signal(self, backoff: float, stop: asyncio.Event) -> float:
        """Persist ``revoked`` only when the platform confirms it; answers the next backoff."""
        verdict = await asyncio.to_thread(self.confirm_revoked)
        if verdict == VERDICT_REVOKED:
            self._mark_revoked()
            return BACKOFF_START
        if verdict == VERDICT_ACTIVE:
            logger.warning("revoke signal not confirmed: the platform renewed the device credential; reconnecting")
            return BACKOFF_START
        if verdict == VERDICT_NEEDS_LOGIN:
            await self._idle("needs_login", stop)
            return BACKOFF_START
        logger.warning("revoke signal not confirmed (no authoritative answer); retrying, the device stays enabled")
        await self._wait(self._delay(backoff), stop)
        return min(backoff * 2, BACKOFF_MAX)

    def _mark_revoked(self) -> None:
        device = device_state.load_device(self.state)
        if device:
            device["revoked"] = True
            device_state.save_device(self.state, device)
        self._status(revoked=True, connected=False)
        self._revoked_due = False  # just confirmed: asked again after ``REVOKED_RECHECK_SECONDS``
        self._revoked_wait = REVOKED_RECHECK_SECONDS
        logger.warning("device revoked by the platform; idle until `octryx-claude device enable`")

    async def _revoked(self, stop: asyncio.Event) -> None:
        """A persisted ``revoked``: ask the platform (at once on start, then periodically); only its own
        ``device_revoked`` keeps the device revoked. Idles between checks, waking early on ``device enable``."""
        if self.recheck_revoked is None:
            await self._idle("revoked", stop)
            return
        if self._revoked_due:
            verdict = await asyncio.to_thread(self.recheck_revoked)
            if verdict in (VERDICT_ACTIVE, VERDICT_NEEDS_LOGIN):
                self._clear_revoked(verdict)
                return
            if verdict == VERDICT_REVOKED:
                wait, self._revoked_wait = self._revoked_wait, min(self._revoked_wait * 2,
                                                                   REVOKED_RECHECK_MAX_SECONDS)
                self._revoked_retry = REVOKED_RETRY_START
                logger.info("device revocation confirmed by the platform; asking again in %d s", int(wait))
            else:
                wait, self._revoked_retry = self._revoked_retry, min(self._revoked_retry * 2,
                                                                     REVOKED_RECHECK_SECONDS)
                logger.info("device revocation could not be checked (no authoritative answer); retrying in %d s",
                            int(wait))
        else:
            wait = self._revoked_wait
        self._revoked_due = True
        await self._idle("revoked", stop, retry_after=wait)

    def _clear_revoked(self, verdict: str) -> None:
        device = device_state.load_device(self.state)
        if device.get("revoked"):
            device.pop("revoked", None)
            device_state.save_device(self.state, device)
        self._status(revoked=False)
        self._revoked_wait, self._revoked_retry = REVOKED_RECHECK_SECONDS, REVOKED_RETRY_START
        logger.warning("persisted revocation not confirmed by the platform (%s); the device is enabled again",
                       verdict)

    async def _idle(self, reason: str, stop: asyncio.Event, *, retry_after: float | None = None) -> None:
        """No retry storm: wait until the device or its credential file changes (or the service stops, or
        ``retry_after`` seconds passed; ``needs_login`` retries hourly)."""
        if self.idle_reason != reason:
            logger.warning("device channel idle: %s", reason)
        self.idle_reason = reason
        self._status(connected=False, needs_login=reason == "needs_login", idle_reason=reason)
        if retry_after is None and reason == "needs_login":
            retry_after = NEEDS_LOGIN_RETRY_SECONDS
        watched = [self.state.root / device_state.DEVICE_FILE,
                   self.state.with_credential_set("device").credentials_path]

        def stamp() -> tuple[float, ...]:
            return tuple(path.stat().st_mtime if path.exists() else 0.0 for path in watched)

        before = stamp()
        waited = 0.0
        while not stop.is_set() and stamp() == before:
            if retry_after is not None and waited >= retry_after:
                break  # an owner reactivated or a clock fixed: try again
            step = IDLE_CHECK_SECONDS if retry_after is None else max(0.0, min(IDLE_CHECK_SECONDS,
                                                                               retry_after - waited))
            await self._wait(step, stop)  # a stop (SIGTERM, an update) ends the idle at once
            waited += step
        self.idle_reason = ""
        self._status(needs_login=False, idle_reason="")
