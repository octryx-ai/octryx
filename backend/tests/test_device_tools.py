"""A device reports the launcher's pinned tools {id: version | None}; the platform keeps them on the connection and
shows them in the device API (the review bot chooses a device by them)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.devices import hub
from app.services.devices.channel_protocol import reported_tools


def test_the_reported_tools_are_kept_bounded_and_anything_else_dropped():
    assert reported_tools({"ast-grep": "0.51.0", "gitleaks": None, "chromium": "", "x" * 60: 1}) == {
        "ast-grep": "0.51.0", "gitleaks": None, "chromium": None, "x" * 40: None}
    assert reported_tools("ast-grep") == {}


def test_the_device_api_shows_the_tools_of_a_connected_device(monkeypatch):
    connection = SimpleNamespace(seat_login=True, codex_seat_login=False, tools={"gitleaks": "8.30.1"})
    monkeypatch.setattr(hub.device_hub, "connection", lambda device_id: connection if device_id == "d1" else None)
    assert hub.device_live_state("d1")["tools"] == {"gitleaks": "8.30.1"}
    assert hub.device_live_state("d2")["tools"] == {}
