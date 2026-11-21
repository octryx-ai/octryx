"""The seat login (login --seat) and the one-time seat login offer of auto on a terminal."""

from __future__ import annotations

import json
import sys

import pytest

from octryx_claude import cli, cli_account, cli_launch, cli_session, launch, profile_choice, seat_login, seat_status
from octryx_claude.seat_status import SeatFailure
from tests.seat_status_support import KEY, _supervise_recording

from .test_seat_profile import _seat

# --- 2: login --seat ---------------------------------------------------------------------------------------------

LOGIN_FAKE = """\
import json, os, sys
with open(os.environ["FAKE_LOGIN_OUT"], "w") as handle:
    json.dump({"argv": sys.argv[1:], "env": dict(os.environ)}, handle)
sys.exit(int(os.environ.get("FAKE_LOGIN_EXIT", "0")))
"""


@pytest.fixture
def fake_login(tmp_path, monkeypatch):
    script = tmp_path / "fake-claude-login"
    script.write_text(f"#!{sys.executable}\n{LOGIN_FAKE}")
    script.chmod(0o755)
    record = tmp_path / "login.json"
    monkeypatch.setenv("FAKE_LOGIN_OUT", str(record))
    monkeypatch.setattr(launch, "resolve_claude", lambda: str(script))
    for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OCTRYX_SESSION_KEY"):
        monkeypatch.setenv(name, "inherited")
    return record


def _no_platform(*args, **kwargs):
    raise AssertionError("login --seat never calls the platform")


@pytest.mark.parametrize("command", [["login", "--seat"], ["seat-login"]])
def test_seat_login_runs_claudes_own_login_in_the_seat_dir_only(state, fake_login, monkeypatch, tmp_path, command):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for module in (cli_launch, cli_session, cli_account):
        monkeypatch.setattr(module, "call_control_plane", _no_platform)
    state.write_credentials({})  # no platform login at all
    seat_status.record_failure(state, KEY, SeatFailure("login_expired", "authentication_failed", 1.0))

    assert cli.main(command) == 0

    run = json.loads(fake_login.read_text())
    assert run["argv"] == ["auth", "login", "--claudeai"]
    assert run["env"]["CLAUDE_CONFIG_DIR"] == str(state.claude_config_dir_for("seat"))
    assert not [name for name in run["env"] if name.startswith("ANTHROPIC_")]
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in run["env"] and "OCTRYX_SESSION_KEY" not in run["env"]
    assert profile_choice.seat_logged_in(state) and seat_status.stored_problem(state) is None
    assert not list(home.glob(".claude*")), "G1: nothing under ~/.claude*"


def test_a_failed_seat_login_writes_no_marker(state, fake_login, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_LOGIN_EXIT", "1")
    assert cli.main(["seat-login"]) == 1
    assert not profile_choice.seat_logged_in(state)
    assert "seat login failed (claude exit 1)" in capsys.readouterr().err
    assert cli.main(["login", "--seat", "--headless"]) == 2


def test_auto_on_a_terminal_offers_the_seat_login_once_and_then_uses_seat(launch_env, monkeypatch, capsys):
    _seat(launch_env)
    asked = []
    monkeypatch.setattr(cli_launch, "_interactive", lambda claude_args: True)
    monkeypatch.setattr(cli_launch, "_ask", lambda prompt: asked.append(prompt) or "y\n")
    monkeypatch.setattr(seat_login, "run_seat_login", lambda state, claude, out=None: (
        profile_choice.mark_seat_session_ok(state), 0)[1])
    seen = _supervise_recording(launch_env, monkeypatch, capsys)

    assert cli.main([]) == 0

    assert asked == [seat_login.PROMPT]
    assert "→ this session: seat" in seen["err_before_claude"]


def test_a_declined_offer_is_not_repeated_and_never_asked_without_a_terminal(launch_env, monkeypatch, capsys):
    _seat(launch_env)
    answers = ["n\n"]
    monkeypatch.setattr(cli_launch, "_interactive", lambda claude_args: True)
    monkeypatch.setattr(cli_launch, "_ask", lambda prompt: answers.pop())
    seen = _supervise_recording(launch_env, monkeypatch, capsys)
    assert cli.main([]) == 0
    assert cli.main([]) == 0  # a second question would pop an empty list
    assert "→ this session: governed" in seen["err_before_claude"]
    assert "seat login: octryx-claude login --seat" in seen["err_before_claude"]
    monkeypatch.setattr(cli_launch, "_interactive", lambda claude_args: False)
    seat_status.record_failure(launch_env["state"], KEY, SeatFailure("login_expired", "authentication_failed", 1.0))
    assert cli.main([]) == 0  # a new seat state, but no terminal: the hint only


def test_the_offer_rules(state):
    ready = seat_status.SeatState("ready", "ready")
    missing = seat_status.SeatState("not_logged_in", "not logged in")

    class Never:
        def __call__(self, prompt):
            raise AssertionError("asked")

    root = state
    assert not seat_login.offer_login(root, ready, interactive=True, ask=Never())
    assert not seat_login.offer_login(root, missing, interactive=False, ask=Never())
    assert seat_login.offer_login(root, missing, interactive=True, ask=lambda prompt: "yes")
    assert not seat_login.offer_login(root, missing, interactive=True, ask=lambda prompt: "")
    assert not seat_login.offer_login(root, missing, interactive=True, ask=Never())  # declined for this state
