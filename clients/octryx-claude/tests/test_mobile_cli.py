from __future__ import annotations

import json

import httpx
import pytest

from octryx_claude import mobile_cli
from octryx_claude.pet import connect

from .conftest import BASE_URL

URL = f"{BASE_URL}/m/pair#c=Q2xhdWRlLWZvci1PY3RyeXg"
CONFIRM_URL = f"{BASE_URL}/m/confirm?p=mpr_1"


def _platform(views: list[dict], *, created_status: int = 201):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body, request.headers.get("authorization")))
        if request.method == "POST" and request.url.path.endswith("/pairings"):
            return httpx.Response(created_status, json={"pairing_id": "mpr_1", "url": URL, "confirm_url": CONFIRM_URL,
                                                        "expires_at": "2026-11-07T12:02:00+00:00"}
                                  if created_status == 201 else {"state": "denied", "reason": "device_login_required"})
        if request.url.path.endswith("/confirm"):
            return httpx.Response(200, json={"state": "confirmed" if body["approve"] else "denied"})
        return httpx.Response(200, json=views.pop(0) if len(views) > 1 else views[0])

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(mobile_cli, "get_access_token", lambda *_a, **_k: "fake-gateway-token-for-tests-0123456789")


def test_the_browser_confirms_and_the_command_follows(state, token, capsys):
    http, calls = _platform([{"state": "pending"}, {"state": "scanned", "match_number": "47", "phone": "iPhone"},
                             {"state": "scanned", "match_number": "47", "phone": "iPhone"}, {"state": "confirmed"}])
    opened = []
    code = mobile_cli.run_pair(state, http=http, interactive=True, sleep=lambda _s: None, open_browser=opened.append)
    out = capsys.readouterr().out
    assert code == 0
    assert "█" in out and "Valid for two minutes" in out and URL not in out  # the code only inside the QR code
    assert opened == [CONFIRM_URL] and "iPhone shows the number 47" in out
    assert not any(call[1].endswith("/confirm") for call in calls)  # this login's token never confirms
    assert all(call[3] == "Bearer fake-gateway-token-for-tests-0123456789" for call in calls)
    assert "Add to Home Screen" in out


@pytest.mark.parametrize("final", ["denied", "expired"])
def test_a_declined_or_expired_confirmation_connects_nothing(state, token, final):
    http, _calls = _platform([{"state": "scanned", "match_number": "12", "phone": "iPhone"}, {"state": final}])
    assert mobile_cli.run_pair(state, http=http, interactive=True, sleep=lambda _s: None,
                               open_browser=lambda _u: None) == 1


def test_an_expired_pairing_opens_nothing(state, token):
    http, _calls = _platform([{"state": "expired"}])
    assert mobile_cli.run_pair(state, http=http, interactive=True, sleep=lambda _s: None,
                               open_browser=lambda _u: pytest.fail("opened")) == 1


def test_nothing_without_a_terminal_or_a_login(state, token, monkeypatch, capsys):
    http, calls = _platform([{"state": "pending"}])
    assert mobile_cli.run_pair(state, http=http, interactive=False) == 2 and calls == []
    refused, _ = _platform([], created_status=403)
    assert mobile_cli.run_pair(state, http=refused, interactive=True) == 1
    assert "device_login_required" in capsys.readouterr().err


def test_the_pet_opens_a_terminal_running_the_command(tmp_path):
    spawned = []
    shim = tmp_path / "bin" / "octryx-claude"
    argv = connect.open_pairing(tmp_path, spawn=lambda a, **_k: spawned.append(a), platform="darwin", shim=shim)
    command = tmp_path / connect.COMMAND_FILE
    assert argv == ["open", str(command)] and spawned == [argv]
    assert command.read_text() == f"#!/bin/sh\nexec {shim} mobile pair\n" and command.stat().st_mode & 0o777 == 0o700
    windows = connect.open_pairing(tmp_path, spawn=lambda a, **_k: spawned.append(a), platform="win32")
    assert windows == ["cmd.exe", "/k", "octryx-claude.cmd", "mobile", "pair"]
