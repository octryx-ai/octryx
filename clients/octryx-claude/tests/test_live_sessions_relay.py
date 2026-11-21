"""The relay process: delivery is reported only for a successful exact call, and it starts ahead of any message."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from octryx_claude.mobile_relay import Relay, marked_text
from octryx_claude.mobile_relay_guard import guard
from octryx_claude.state import LocalState


class _Stdin:
    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def write(self, data: bytes) -> None:
        self.lines.append(json.loads(data))

    async def drain(self) -> None:
        return None


class _Stdout:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def readline(self) -> bytes:
        return await self.queue.get()


class _Process:
    def __init__(self) -> None:
        self.stdin, self.stdout, self.returncode = _Stdin(), _Stdout(), None

    def terminate(self) -> None:
        self.returncode = 0
        self.stdout.queue.put_nowait(b"")

    async def wait(self) -> int:
        return 0


def _tool_use(call_id: str, to: str, message: str) -> bytes:
    return json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": call_id, "name": "SendMessage", "input": {"to": to, "message": message}}]}}
    ).encode() + b"\n"


def _result(call_id: str, ok: bool) -> bytes:
    return json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id, "is_error": not ok, "content": "x"}]}}).encode() + b"\n"


def test_relay_reports_delivery_only_for_a_successful_exact_call(tmp_path, monkeypatch):
    monkeypatch.setattr("octryx_claude.mobile_relay.launch.resolve_claude", lambda: "/bin/claude")
    process = _Process()
    sent: list[tuple[str, bool]] = []
    incoming: list[tuple[str, str, str]] = []

    async def spawn(*args: Any, **kwargs: Any) -> _Process:
        assert args[0] == "/bin/claude" and "CLAUDE_CONFIG_DIR" not in kwargs["env"]
        assert not kwargs["cwd"].startswith(str(tmp_path))  # never next to octryx's state and credentials
        return process

    async def scenario() -> None:
        async def on_sent(key: str, ok: bool) -> None:
            sent.append((key, ok))

        async def on_incoming(sender: str, name: str, text: str) -> None:
            incoming.append((sender, name, text))

        relay = Relay(LocalState(tmp_path), on_incoming=on_incoming, on_sent=on_sent, spawn=spawn,
                      delivery_seconds=0.05)
        assert not await relay.send("uds:/tmp/../etc;rm.sock x", "hi")
        assert not await relay.send("uds:/tmp/a.sock", "   ")
        assert await relay.send("uds:/tmp/a.sock", "first", "Alice", key="m1")
        assert await relay.send("uds:/tmp/a.sock", "second", "Alice", key="m2")
        folder = relay.folder
        process.stdout.queue.put_nowait(_tool_use("c1", "uds:/tmp/a.sock", marked_text("first", "Alice")))
        process.stdout.queue.put_nowait(_result("c1", True))
        process.stdout.queue.put_nowait(_tool_use("c2", "uds:/tmp/a.sock", "ANSWER-OK"))  # refused by the guard
        process.stdout.queue.put_nowait(_result("c2", False))
        reply = '<cross-session-message from="uds:/tmp/a.sock" from-name="pet">\nok\n</cross-session-message>'
        process.stdout.queue.put_nowait(json.dumps({"type": "user", "message": {"content": reply}}).encode() + b"\n")
        for _ in range(20):
            await asyncio.sleep(0)
        assert sent == [("m1", True)]
        await asyncio.sleep(0.1)  # "second" never went out: reported as not delivered, its permission withdrawn
        assert guard(folder, {"tool_name": "SendMessage", "tool_input": {
            "to": "uds:/tmp/a.sock", "message": marked_text("second", "Alice")}})
        await relay.stop()
        assert not folder.exists()

    asyncio.run(scenario())
    assert sent == [("m1", True), ("m2", False)]
    assert incoming == [("uds:/tmp/a.sock", "pet", "ok")]
    request = process.stdin.lines[0]["message"]["content"]
    assert request.startswith("RELAY SEND\nto: uds:/tmp/a.sock\n")


def test_relay_start_runs_the_process_ahead_of_any_message(tmp_path, monkeypatch):
    monkeypatch.setattr("octryx_claude.mobile_relay.launch.resolve_claude", lambda: "/bin/claude")
    process = _Process()

    async def spawn(*args: Any, **kwargs: Any) -> _Process:
        return process

    async def scenario() -> None:
        async def nothing(*_: Any) -> None:
            return None

        relay = Relay(LocalState(tmp_path), on_incoming=nothing, spawn=spawn)
        assert not relay.running
        await relay.start()
        await relay.start()
        assert relay.running and process.stdin.lines == []
        await relay.stop()

    asyncio.run(scenario())
