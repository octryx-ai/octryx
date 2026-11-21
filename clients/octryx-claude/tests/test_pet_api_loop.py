"""The pet's HTTP read, platform links, the loop, its menu actions and the status icons."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from octryx_claude.pet import api, icons
from octryx_claude.pet import settings as pet_settings
from octryx_claude.pet.account import LocalAccount
from octryx_claude.pet.display import OFFLINE, SIGNED_OUT
from octryx_claude.pet.runner import Runner
from octryx_claude.pet.schedule import Schedule
from tests.pet_support import NOON, _pet

from .conftest import BASE_URL

# --- api -------------------------------------------------------------------------------------------------------


def _http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- the loop --------------------------------------------------------------------------------------------------


class FakeView:
    def __init__(self) -> None:
        self.shown, self.notified = [], []

    def show(self, display) -> None:
        self.shown.append(display)

    def notify(self, notification) -> None:
        self.notified.append(notification)


def test_fetch_sends_the_token_and_round_trips_the_etag(state):
    state.write_config({"base_url": BASE_URL})
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"etag": '"v1"'})
        return httpx.Response(200, json={"v": 1, "state": "working", "items": []}, headers={"etag": '"v1"'})

    with _http(handler) as http:
        first = api.fetch(LocalAccount(state), http=http, project_id="ws-1")
        second = api.fetch(LocalAccount(state), http=http, etag=first.etag)
    assert str(seen[0].url) == f"{BASE_URL}/api/v1/agent-gateway/pet?project_id=ws-1"
    assert seen[0].headers["authorization"] == "Bearer gw-cached"
    assert (first.outcome, first.pet.state, first.etag) == ("ok", "working", '"v1"')
    assert second.outcome == "not_modified" and second.pet is None


@pytest.mark.parametrize(("status", "headers", "outcome", "reason"), [
    (401, {}, "signed_out", ""),
    (403, {"x-octryx-gateway-reason": "workspace_not_authorized"}, "refused", "workspace_not_authorized"),
    (403, {"x-octryx-gateway-reason": "Free text!"}, "refused", ""),
    (502, {}, "unreachable", "platform_error"),
])
def test_fetch_failures_keep_to_fixed_codes(state, status, headers, outcome, reason):
    state.write_config({"base_url": BASE_URL})
    with _http(lambda _r: httpx.Response(status, headers=headers, text="secret body")) as http:
        result = api.fetch(LocalAccount(state), http=http)
    assert (result.outcome, result.reason) == (outcome, reason)


def test_fetch_without_login_or_network(state, tmp_path):
    assert api.fetch(LocalAccount(state), http=httpx.Client()).outcome == "signed_out"  # no base URL configured
    state.write_config({"base_url": BASE_URL})

    def down(_request):
        raise httpx.ConnectError("down")

    with _http(down) as http:
        assert api.fetch(LocalAccount(state), http=http).outcome == "unreachable"
    with _http(lambda _r: httpx.Response(200, text="not json")) as http:
        assert api.fetch(LocalAccount(state), http=http).reason == "invalid_response"


def test_links_resolve_on_the_platform():
    assert api.resolve(BASE_URL, "/chat?area=operations&tab=usage") == f"{BASE_URL}/chat?area=operations&tab=usage"
    assert api.resolve(BASE_URL, "https://bitbucket.org/x") == "https://bitbucket.org/x"
    assert api.resolve(BASE_URL, None) is None and api.resolve("", "/chat") is None


def test_the_loop_keeps_the_last_state_and_reports_the_connection(state):
    state.write_config({"base_url": BASE_URL})
    answers = [api.FetchResult("ok", pet=_pet("needs_you", "a"), etag='"1"'),
               api.FetchResult("not_modified", etag='"1"'),
               api.FetchResult("ok", pet=_pet("needs_you", "a", "b"), etag='"2"'),
               api.FetchResult("unreachable", reason="platform_unreachable"),
               api.FetchResult("signed_out", reason="not_logged_in")]
    etags = []

    def fetch(_state, *, http, etag, project_id):
        etags.append(etag)
        return answers.pop(0)

    view = FakeView()
    runner = Runner(LocalAccount(state), view, http=httpx.Client(), fetch=fetch, schedule=Schedule(rand=lambda: 0.5),
                    now=lambda: NOON)
    delays = [runner.tick() for _ in range(5)]
    assert etags == ["", '"1"', '"1"', '"2"', ""]
    assert [display.status for display in view.shown] == ["needs_you", "needs_you", "needs_you", OFFLINE,
                                                         SIGNED_OUT]
    assert view.shown[3].items  # offline keeps the last items
    assert delays == [15, 15, 15, 15, 300]  # no server hint in _pet: the needs_you default, backoff, signed out
    assert [note.url for note in view.notified] == [f"{BASE_URL}/chat?session_id=b"]


def test_menu_actions_change_pause_and_quiet_hours(state):
    runner = Runner(LocalAccount(state), FakeView(), http=httpx.Client(), now=lambda: NOON)
    runner.pause(1)
    assert runner.paused() and runner.paused_until == NOON + timedelta(hours=1)
    runner.pause(0)
    assert not runner.paused()
    runner.toggle_quiet_hours()
    assert runner.quiet_hours().enabled and pet_settings.load(state.root).quiet_hours.label() == "19:00–08:00"


# --- icons -----------------------------------------------------------------------------------------------------


def test_icons_for_every_status_and_size():
    for status in ("resting", "unknown", "working", "needs_you", "done", "problem", "offline", "signed_out"):
        for appearance in ("light", "dark"):
            image = icons.render(status, 12, size=44, appearance=appearance)
            assert image.size == (44, 44) and image.mode == "RGBA" and image.getbbox()
    assert icons.render("done", size=44).tobytes() == icons.render("done", size=44).tobytes()
    plain, badged = icons.render("resting", size=44), icons.render("problem", size=44)
    assert plain.getpixel((40, 40)) != badged.getpixel((40, 40))
    ico = icons.ico_bytes("needs_you", 3)
    assert ico[:4] == b"\x00\x00\x01\x00" and int.from_bytes(ico[4:6], "little") == len(icons.ICO_SIZES)
