"""The in-process hub of connected devices: who is connected here and what runs on it.

The device channel (``api/routes/device_channel.py``) registers each live socket here. The source of truth for
devices, jobs and approvals is the database; this hub only holds the sockets of this process, as the chat
session stream does (cross-replica delivery is not built yet).

``device_revoked`` / ``devices_paused`` are called after the change is committed: a connected device gets
``revoke`` / ``pause`` at once and stops its running jobs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Protocol

from ...time_utils import utc_now

# A device connected to another platform process (a sibling API process under several uvicorn workers;
# the platform worker holds no device sockets) stamps ``last_seen_at`` when it connects and every
# ``channel.LAST_SEEN_SECONDS`` (30 s) after; a stamp this recent counts as connected.
REMOTE_LIVE_WINDOW = timedelta(seconds=75)


class DeviceConnection(Protocol):
    device_id: str
    seat_login: bool

    async def send(self, message_type: str, body: dict[str, Any]) -> None: ...

    async def close(self, reason: str) -> None: ...


class DeviceHub:
    def __init__(self) -> None:
        self._connections: dict[str, DeviceConnection] = {}
        # When a device's socket left this process: an older ``last_seen_at`` is that connection's, not a live one.
        self._detached_at: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def attach(self, connection: DeviceConnection) -> DeviceConnection | None:
        """Register ``connection``; returns the connection it replaced (a reconnect), if any."""
        async with self._lock:
            previous = self._connections.get(connection.device_id)
            self._connections[connection.device_id] = connection
        if previous is not None:
            from ..observability.run_quality_metrics import device_reconnected

            device_reconnected()
        return previous

    async def detach(self, connection: DeviceConnection) -> None:
        async with self._lock:
            if self._connections.get(connection.device_id) is connection:
                self._connections.pop(connection.device_id, None)
                self._detached_at[connection.device_id] = utc_now()

    def connection(self, device_id: str) -> DeviceConnection | None:
        """The device's live connection; one whose tick stopped succeeding (``healthy``) does not count."""
        connection = self._connections.get(device_id)
        healthy = getattr(connection, "healthy", None)
        if connection is not None and callable(healthy) and not healthy():
            return None
        return connection

    def connected(self, device_id: str) -> bool:
        return self.connection(device_id) is not None

    def reachable(self, device: Any) -> bool:
        """Connected here, or (no socket here) connected to another process by its recent ``last_seen_at``."""
        device_id = str(device.id)
        if self.connected(device_id):
            return True
        if device_id in self._connections:
            return False  # attached here, but its tick stopped succeeding
        seen = getattr(device, "last_seen_at", None)
        if seen is None:
            return False
        seen = seen.replace(tzinfo=None) if seen.tzinfo else seen
        now = utc_now()
        detached = self._detached_at.get(device_id)
        if detached is not None and seen <= detached:
            return False
        return now - seen <= REMOTE_LIVE_WINDOW

    def attached(self, device_id: str) -> DeviceConnection | None:
        """The attached connection, healthy or not (a revoke or pause must reach it either way)."""
        return self._connections.get(device_id)

    def clear(self) -> None:
        self._connections.clear()
        self._detached_at.clear()


device_hub = DeviceHub()


def device_live_state(device_id: str) -> dict[str, Any]:
    """``{connected, seat_login, codex_seat_login}`` for the serializers; running jobs are counted from the database."""
    connection = device_hub.connection(device_id)
    return {"connected": connection is not None, "seat_login": bool(connection and connection.seat_login),
            "codex_seat_login": bool(connection and getattr(connection, "codex_seat_login", False)),
            "tools": dict(getattr(connection, "tools", None) or {}) if connection is not None else {}}


async def device_revoked(device_id: str) -> None:
    connection = device_hub.attached(device_id)
    if connection is not None:
        await connection.close("revoke")


async def devices_paused(devices: Iterable[Any], *, paused: bool = True) -> None:
    """The platform pause changed: a connected device stops its jobs (``pause``) or accepts again (``resume``)."""
    for device in devices:
        connection = device_hub.attached(device.id)
        if connection is not None:
            await connection.send("pause" if paused else "resume", {})


__all__ = ["DeviceConnection", "DeviceHub", "device_hub", "device_live_state", "device_revoked", "devices_paused"]
