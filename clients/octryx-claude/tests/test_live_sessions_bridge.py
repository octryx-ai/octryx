"""The device service's bridge: reports only when on, sends to listed sessions once, refuses when off."""

from __future__ import annotations

import asyncio

from octryx_claude import device_state
from tests.live_sessions_support import SESSION, _bridge, _FakeRelay


def test_bridge_reports_only_when_on(tmp_path):
    bridge, channel = _bridge(tmp_path, False, [SESSION])
    asyncio.run(bridge.tick())
    assert channel.sent == []
    device_state.save_device(bridge.state, {"device_id": "dev_1", "live": True})
    asyncio.run(bridge.tick())
    asyncio.run(bridge.tick())  # unchanged (only updated_at moves): not sent again
    assert channel.sent == [("live_sessions", {"sessions": [SESSION], "live": True})]
    relay = _FakeRelay.instances[0]
    assert relay.running and relay.starts == 1  # started with live on, before any phone message
    relay.running = False  # it ended (an update restarted things): the next round starts it again
    asyncio.run(bridge.tick())
    assert relay.starts == 2
    device_state.save_device(bridge.state, {"device_id": "dev_1", "live": False})
    asyncio.run(bridge.tick())
    assert channel.sent[-1] == ("live_sessions", {"sessions": [], "live": False})


def test_bridge_sends_only_to_listed_sessions_once(tmp_path):
    notes: list[str] = []
    bridge, channel = _bridge(tmp_path, True, [SESSION], notes)

    async def scenario() -> None:
        await bridge.handle("live_send", {"message_id": "m1", "peer": SESSION["peer"], "text": "hi", "sender": "L"})
        await bridge.handle("live_send", {"message_id": "m1", "peer": SESSION["peer"], "text": "hi", "sender": "L"})
        await bridge.handle("live_send", {"message_id": "m2", "peer": "uds:/tmp/cc-socks/9.sock", "text": "hi"})
        await bridge.handle("live_send", {"message_id": "bad id!", "peer": SESSION["peer"], "text": "hi"})
        relay = _FakeRelay.instances[0]
        await relay.on_sent("m1", True)
        await relay.on_incoming(SESSION["peer"], "pet", "answer")
        await relay.on_incoming("not-an-address", "x", "dropped")

    asyncio.run(scenario())
    assert _FakeRelay.instances[0].sends == [(SESSION["peer"], "hi", "L", "m1")]
    assert notes == ["Your phone sent a message to pet in PRIV"]
    deliveries = [body for kind, body in channel.sent if kind == "live_delivery"]
    assert deliveries == [{"message_id": "m2", "state": "failed", "reason": "session_gone"},
                          {"message_id": "m1", "state": "delivered", "reason": ""}]
    incoming = [body for kind, body in channel.sent if kind == "live_incoming"]
    assert [(item["from"], item["text"]) for item in incoming] == [(SESSION["peer"], "answer")]


def test_bridge_refuses_when_off_and_buffers_while_down(tmp_path):
    bridge, channel = _bridge(tmp_path, False, [SESSION])
    channel.up = False

    async def scenario() -> None:
        await bridge.handle("live_send", {"message_id": "m1", "peer": SESSION["peer"], "text": "hi"})
        channel.up = True
        await bridge.handle("connected", {})

    asyncio.run(scenario())
    assert _FakeRelay.instances == []
    assert channel.sent == [("live_delivery", {"message_id": "m1", "state": "failed", "reason": "live_off"})]
