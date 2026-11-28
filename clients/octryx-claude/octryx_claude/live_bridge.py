"""The device service's side of Octryx Mobile "live": the phone talks to Claude Code sessions running here."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from . import device_state
from .live_attachments import (
    MESSAGE_ID,
    AttachmentInbox,
)
from .live_progress import ProgressTail
from .live_progress import enabled as progress_enabled
from .live_sessions import live_sessions
from .mobile_relay import Relay
from .mobile_relay_events import MAX_TEXT
from .mobile_relay_guard import PEER
from .state import LocalState

logger = logging.getLogger("octryx_claude.live")

SCAN_SECONDS = 3.0  # also how fresh the phone's progress view is
REPORT_SECONDS = 60.0
MAX_BUFFER = 200
MAX_SEEN = 500
VOLATILE = ("updated_at",)


class LiveBridge(AttachmentInbox):
    def __init__(self, state: LocalState, *, relay_factory: Callable[..., Any] | None = None,
                 scan: Callable[[LocalState], list[dict[str, Any]]] = live_sessions,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.state = state
        self.scan = scan
        self.clock = clock
        self.channel: Any = None
        self._relay_factory = relay_factory or Relay
        self._relay: Any = None
        self._buffer: deque[tuple[str, dict[str, Any]]] = deque(maxlen=MAX_BUFFER)
        self._seen: deque[str] = deque(maxlen=MAX_SEEN)
        self._reported = ""
        self._reported_at = float("-inf")
        self.progress = ProgressTail(state)
        # attachment id -> {"message_id", "total", "parts": {index: bytes}, "size"}
        self._parts: dict[str, dict[str, Any]] = {}

    def attach(self, channel: Any) -> None:
        self.channel = channel

    @property
    def enabled(self) -> bool:
        return device_state.load_device(self.state).get("live") is True

    def _session(self, peer: str) -> dict[str, Any] | None:
        return next((item for item in self.scan(self.state) if item.get("peer") == peer), None)

    # --- the loop --------------------------------------------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - one bad round never ends the live channel
                logger.warning("live round failed", exc_info=True)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), SCAN_SECONDS)

    async def tick(self) -> None:
        if self.channel is None or not getattr(self.channel, "connected", False):
            return
        await self._flush()  # answers and delivery reports wait for no switch
        if not self.enabled:
            if self._relay is not None:
                await self.stop()
            if self._reported not in ("", "[]"):
                if await self.channel.send_message("live_sessions", {"sessions": [], "live": False}):
                    self._reported = "[]"
            return
        await self._keep_relay()
        sessions = self.scan(self.state)
        stable = json.dumps([{k: v for k, v in item.items() if k not in VOLATILE} for item in sessions],
                            sort_keys=True)
        now = self.clock()
        if stable != self._reported or now - self._reported_at >= REPORT_SECONDS:
            if not await self.channel.send_message("live_sessions", {"sessions": sessions, "live": True}):
                return  # progress only for sessions the platform has listed
            self._reported, self._reported_at = stable, now
        if progress_enabled(self.state):
            for peer, events in self.progress.collect(sessions):
                await self._emit("live_progress", {"peer": peer, "events": events})

    async def _flush(self) -> None:
        while self._buffer:
            message_type, body = self._buffer[0]
            if not await self.channel.send_message(message_type, body):
                return
            self._buffer.popleft()

    async def _emit(self, message_type: str, body: dict[str, Any]) -> None:
        if self.channel is None or not await self.channel.send_message(message_type, body):
            self._buffer.append((message_type, body))

    # --- what the platform sends -----------------------------------------------------------------------------

    async def handle(self, message_type: str, body: dict[str, Any]) -> None:
        if message_type == "connected":
            self._reported, self._reported_at = "", float("-inf")  # a new connection gets the list at once
            await self.tick()
        elif message_type == "live_attachment":
            self._attachment(body)
        elif message_type == "live_send":
            await self._send(body)

    async def _send(self, body: dict[str, Any]) -> None:
        message_id = str(body.get("message_id") or "")
        if not MESSAGE_ID.match(message_id) or message_id in self._seen:
            return  # a redelivery after a reconnect: it was handled the first time
        self._seen.append(message_id)
        peer, text = str(body.get("peer") or ""), str(body.get("text") or "")
        if not self.enabled:
            await self._delivery(message_id, "failed", "live_off")
            return
        if not PEER.match(peer) or not text.strip() or len(text) > MAX_TEXT:
            await self._delivery(message_id, "failed", "invalid")
            return
        session = self._session(peer)
        if session is None:
            await self._delivery(message_id, "failed", "session_gone")
            return
        named = body.get("attachments") if isinstance(body.get("attachments"), list) else []
        if named:
            paths = self._store(message_id, named[:3])
            if paths is None:
                await self._delivery(message_id, "failed", "attachment_missing")
                return
            listed = "\n".join(f"- {path}" for path in paths)
            note = (f"\n\n[The phone attached {len(paths)} picture{'s' if len(paths) > 1 else ''}. "
                    f"Open with the Read tool:]\n{listed}")
            text = text[:MAX_TEXT - len(note)] + note  # the paths always arrive whole
        try:
            relay = self._ensure_relay()
            sent = await relay.send(peer, text, str(body.get("sender") or "the owner"), key=message_id)
        except Exception:  # noqa: BLE001 - claude missing, spawn failed: the phone learns it was not delivered
            logger.warning("live relay failed", exc_info=True)
            sent = False
        if not sent:
            await self._delivery(message_id, "failed", "relay_failed")
            return
        where = str(session.get("cwd") or "").rstrip("/").rsplit("/", 1)[-1]
        self.notify(f"Your phone sent a message to {session.get('name') or 'a Claude Code session'}"
                    + (f" in {where}" if where else ""))

    async def _keep_relay(self) -> None:
        relay = self._ensure_relay()
        if getattr(relay, "running", True):
            return
        try:
            await relay.start()
        except Exception:  # noqa: BLE001 - no claude, a failed spawn: the next round tries again
            logger.warning("live relay did not start", exc_info=True)

    def _ensure_relay(self) -> Any:
        if self._relay is None:
            self._relay = self._relay_factory(self.state, on_incoming=self._incoming, on_sent=self._sent)
        return self._relay

    async def _sent(self, message_id: str, exact: bool) -> None:
        await self._delivery(message_id, "delivered" if exact else "altered", "" if exact else "relay_changed_text")

    async def _delivery(self, message_id: str, state: str, reason: str = "") -> None:
        await self._emit("live_delivery", {"message_id": message_id, "state": state, "reason": reason})

    async def _incoming(self, sender: str, name: str, text: str) -> None:
        if not PEER.match(sender):
            return
        await self._emit("live_incoming", {"from": sender, "name": name[:120], "text": text[:MAX_TEXT],
                                           "at": time.time()})

    @staticmethod
    def notify(text: str) -> None:
        from .mac_notify import notify  # noqa: PLC0415

        notify("Octryx", text[:200])

    async def stop(self) -> None:
        relay, self._relay = self._relay, None
        if relay is not None:
            await relay.stop()


__all__ = ["LiveBridge", "REPORT_SECONDS", "SCAN_SECONDS"]
