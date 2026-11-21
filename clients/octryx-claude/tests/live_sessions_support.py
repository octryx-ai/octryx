"""Shared fake relay, channel and bridge helpers for the Octryx Mobile live tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from octryx_claude import device_state
from octryx_claude.live_bridge import LiveBridge
from octryx_claude.state import LocalState


class _Channel:
    def __init__(self) -> None:
        self.connected = True
        self.up = True
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def send_message(self, message_type: str, body: dict[str, Any]) -> bool:
        if not self.up:
            return False
        self.sent.append((message_type, body))
        return True


class _FakeRelay:
    instances: list[_FakeRelay] = []

    def __init__(self, state: LocalState, *, on_incoming: Any, on_sent: Any) -> None:
        self.on_incoming, self.on_sent, self.sends = on_incoming, on_sent, []
        self.stopped = False
        self.running = False
        self.starts = 0
        _FakeRelay.instances.append(self)

    async def start(self) -> None:
        self.starts += 1
        self.running = True

    async def send(self, peer: str, text: str, sender: str, key: str = "") -> bool:
        self.sends.append((peer, text, sender, key))
        return True

    async def stop(self) -> None:
        self.stopped = True


def _bridge(tmp_path: Path, live: bool, sessions: list[dict[str, Any]],
            notes: list[str] | None = None) -> tuple[LiveBridge, _Channel]:
    state = LocalState(tmp_path)
    device_state.save_device(state, {"device_id": "dev_1", "live": live})
    _FakeRelay.instances.clear()
    bridge = LiveBridge(state, relay_factory=_FakeRelay, scan=lambda _state: sessions)
    bridge.notify = (notes if notes is not None else []).append
    channel = _Channel()
    bridge.attach(channel)
    return bridge, channel


SESSION = {"profile": "default", "pid": 1, "name": "pet", "peer": "uds:/tmp/cc-socks/1.sock", "status": "busy",
           "cwd": "/Users/x/PRIV", "updated_at": 1}
