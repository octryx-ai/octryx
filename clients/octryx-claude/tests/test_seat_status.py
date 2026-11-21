"""Seat and governance status, seat login and seat failures (Alice).

1. Every start prints the status block on stderr before Claude Code starts; ``status`` shows it too.
2. ``octryx-claude login --seat`` (``seat-login``) signs the seat profile in without the platform login; ``auto``
   offers it once on a terminal.
3. A rejected subscription login or a reached limit (Claude Code's ``StopFailure``) is said with its fix: on the next
   prompt, when the session ends, and in the next start's status block.
4. The main model defaults to ``claude-opus-5-5``.
"""

from __future__ import annotations

import io
import json
import time

import httpx
import pytest

from octryx_claude import cli, hooks, launch_settings, seat_hooks, seat_status, session_hooks
from octryx_claude.platform import PlatformResult
from octryx_claude.seat_status import SeatFailure
from tests.seat_status_support import KEY

GATEWAY_EXPIRED = ("API Error: 401 {\"type\":\"error\",\"error\":{\"type\":\"authentication_error\",\"message\":"
                   "\"Octryx gateway: unauthorized (seat_session_expired). The seat session ended.\"}}")


def _state(state, *, refusal="", logged_in=True, policy_ok=True, now=None):
    return seat_status.seat_state(state, policy_ok=policy_ok, seat_refusal=refusal, logged_in=logged_in, now=now)


# --- 3: the hooks --------------------------------------------------------------------------------------------------

def _hook_env(monkeypatch, profile="seat"):
    monkeypatch.setenv("OCTRYX_BASE_URL", "https://octryx.example.test")
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("OCTRYX_PROFILE", profile)


def _stdin(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))


# --- 3: classification, recording and the seat state -------------------------------------------------------------

@pytest.mark.parametrize(("hook_input", "kind", "code"), [
    ({"error": "authentication_failed"}, "login_expired", "authentication_failed"),
    ({"error": "oauth_org_not_allowed"}, "login_expired", "oauth_org_not_allowed"),
    ({"error": "rate_limit", "last_assistant_message": "You've hit your limit"}, "limit_reached", "rate_limit"),
    ({"error": "billing_error"}, "limit_reached", "billing_error"),
    ({"error": "authentication_failed", "error_details": GATEWAY_EXPIRED}, "platform_refused",
     "unauthorized/seat_session_expired"),
    ({"error": "authentication_failed", "error_details": GATEWAY_EXPIRED.replace("Octryx", "Octryx")},
     "platform_refused", "unauthorized/seat_session_expired"),
])
def test_a_stop_failure_is_classified_by_its_fixed_codes(hook_input, kind, code):
    failure = seat_status.classify_failure({"hook_event_name": "StopFailure", **hook_input}, now=100.0)
    assert failure == SeatFailure(kind, code, 100.0)


@pytest.mark.parametrize("error", ["overloaded", "server_error", "unknown", "invalid_request", "", "Rate Limit!"])
def test_other_api_errors_are_not_seat_problems(error):
    assert seat_status.classify_failure({"error": error, "last_assistant_message": "rate_limit"}) is None


def test_every_message_names_its_fix():
    login = seat_status.failure_message(SeatFailure("login_expired", "authentication_failed"))
    assert "octryx-claude login --seat" in login and "/login" in login and "--profile governed" in login
    limit = seat_status.failure_message(SeatFailure("limit_reached", "rate_limit", time.time()))
    assert "limit is reached (rate_limit" in limit and "--profile governed" in limit
    refused = seat_status.failure_message(SeatFailure("platform_refused", "unauthorized/seat_session_expired"))
    assert "Octryx refused the seat call (unauthorized/seat_session_expired)" in refused


def test_the_seat_state_order(state):
    assert _state(state).code == "ready"
    assert _state(state, logged_in=False).label == seat_status.NO_LOGIN_RECORDED
    assert "macOS Keychain" in seat_status.NO_LOGIN_RECORDED and "login --seat" in seat_status.NO_LOGIN_RECORDED
    assert _state(state, refusal="seat_mode_forbidden").label == "not allowed by the Workspace (seat_mode_forbidden)"
    assert _state(state, policy_ok=False, refusal="x").code == "unknown"
    seat_status.record_failure(state, KEY, SeatFailure("limit_reached", "rate_limit", 1000.0))
    assert _state(state, now=1000.0 + 3600).code == "limit_reached"
    assert _state(state, now=1000.0 + seat_status.LIMIT_WINDOW_SECONDS).code == "ready"  # the window passed
    assert _state(state, logged_in=False, now=1001.0).code == "not_logged_in"
    seat_status.record_failure(state, KEY, SeatFailure("login_expired", "authentication_failed", 1000.0))
    assert _state(state, now=10**9).code == "login_expired"  # outranks the presence check, never expires
    assert _state(state, refusal="seat_mode_forbidden").code == "forbidden"  # the Workspace outranks everything
    seat_status.clear_after_success(state, KEY)
    assert _state(state).code == "ready" and seat_status.session_failure(state, KEY) is None


def test_a_platform_refusal_is_kept_for_the_session_only(state):
    seat_status.record_failure(state, KEY, SeatFailure("platform_refused", "denied/seat_mode_forbidden", 5.0))
    assert seat_status.session_failure(state, KEY).code == "denied/seat_mode_forbidden"
    assert seat_status.stored_problem(state) is None and _state(state).code == "ready"


def test_the_stop_failure_hook_records_and_the_next_prompt_says_it_once(state, monkeypatch, capsys):
    _hook_env(monkeypatch)
    _stdin(monkeypatch, {"hook_event_name": "StopFailure", "error": "authentication_failed"})
    assert cli.main(["hook", "stop-failure"]) == 0
    assert capsys.readouterr().out == ""  # Claude Code ignores it anyway
    assert seat_status.stored_problem(state).kind == "login_expired"
    for expected in (True, False):
        _stdin(monkeypatch, {"hook_event_name": "UserPromptSubmit", "prompt": "go on"})
        assert session_hooks.run_user_prompt_submit(state, httpx.Client()) == 0
        out = capsys.readouterr().out
        if expected:
            message = json.loads(out)["systemMessage"]
            assert message.startswith("octryx-claude: seat: your Claude subscription login was rejected")
            assert "octryx-claude login --seat" in message and "decision" not in json.loads(out)
        else:
            assert out == ""


def test_a_governed_session_never_records_a_seat_failure(state, monkeypatch, capsys):
    _hook_env(monkeypatch, profile="governed")
    _stdin(monkeypatch, {"hook_event_name": "StopFailure", "error": "authentication_failed"})
    assert seat_hooks.run_stop_failure(state) == 0
    assert seat_status.stored_problem(state) is None and seat_status.session_failure(state, KEY) is None


def test_a_completed_seat_turn_clears_the_failure(state, monkeypatch):
    _hook_env(monkeypatch)
    seat_status.record_failure(state, KEY, SeatFailure("limit_reached", "rate_limit", time.time()))
    _stdin(monkeypatch, {"hook_event_name": "Stop", "stop_hook_active": False, "session_id": KEY})
    monkeypatch.setattr(hooks, "call_control_plane", lambda *a, **k: PlatformResult(
        "ok", body={"state": "allowed"}, status_code=200, state="allowed"))
    assert hooks.run_stop(state, httpx.Client()) == 0
    assert seat_status.session_failure(state, KEY) is None and seat_status.stored_problem(state) is None


def test_only_the_seat_settings_carry_the_stop_failure_hook(tmp_path):
    common = {"shim": tmp_path / "octryx-claude", "state_root": tmp_path, "env": {}, "policy": {},
              "base_url": "https://octryx.example.test"}
    seat = launch_settings.build_settings(**common, profile="seat")["hooks"]["StopFailure"]
    assert seat[0]["hooks"][0]["command"].endswith("hook stop-failure")
    assert "StopFailure" not in launch_settings.build_settings(**common)["hooks"]
