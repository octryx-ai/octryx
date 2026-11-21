"""``--profile auto`` (the default): seat when the Workspace allows it and the seat login exists, else governed."""

from __future__ import annotations

import json
import os

import pytest

from octryx_claude import cli, profile_choice, seat_status
from octryx_claude.profile_choice import choose_profile
from octryx_claude.seat_status import SeatState

from .test_seat_profile import _seat


@pytest.mark.parametrize(("requested", "code", "profile", "reason"), [
    ("auto", seat_status.STATE_READY, "seat", "auto: Workspace allows seat and the seat login is present"),
    ("auto", seat_status.STATE_NOT_LOGGED_IN, "governed", "auto: no seat login recorded"),
    ("auto", seat_status.STATE_LOGIN_EXPIRED, "governed", "auto: seat login expired"),
    ("auto", seat_status.STATE_LIMIT_REACHED, "governed", "auto: seat limit reached (at 10:00; counts for 5h)"),
    ("auto", seat_status.STATE_FORBIDDEN, "governed", "auto: Workspace forbids seat: seat_mode_forbidden"),
    ("auto", seat_status.STATE_UNKNOWN, "governed", "auto: seat state unknown"),
    ("governed", seat_status.STATE_READY, "governed", "--profile governed"),
    ("seat", seat_status.STATE_FORBIDDEN, "seat", "--profile seat"),  # explicit (refused later)
])
def test_the_choice_and_its_reason(requested, code, profile, reason):
    labels = {seat_status.STATE_LIMIT_REACHED: "limit reached (at 10:00; counts for 5h)"}
    seat = SeatState(code, labels.get(code, code), "seat_mode_forbidden" if code == "forbidden" else "")
    choice = choose_profile(requested, seat=seat)
    assert (choice.profile, choice.reason) == (profile, reason)


def test_the_seat_login_is_detected_by_presence_only(state):
    assert not profile_choice.seat_logged_in(state)
    seat_dir = state.claude_config_dir_for("seat")
    seat_dir.mkdir(parents=True, exist_ok=True)
    credential = seat_dir / ".credentials.json"
    credential.write_text("{}")
    os.chmod(credential, 0)  # unreadable: detection never opens it
    try:
        assert profile_choice.seat_logged_in(state)
    finally:
        os.chmod(credential, 0o600)
        credential.unlink()
    assert not profile_choice.seat_logged_in(state)
    profile_choice.mark_seat_session_ok(state)
    assert profile_choice.seat_logged_in(state)


def _profile(launch_env) -> str:
    return launch_env["bodies"]["/sessions/register"]["profile"]


def test_auto_is_the_default_and_picks_seat_when_both_hold(launch_env, capsys):
    _seat(launch_env)
    profile_choice.mark_seat_session_ok(launch_env["state"])
    assert cli.main(["--", "-p", "hi"]) == 0
    assert _profile(launch_env) == "seat"
    assert ("octryx-claude:   → this session: seat, model claude-opus-5-5 "
            "(auto: Workspace allows seat and the seat login is present)") in capsys.readouterr().err
    child = json.loads(launch_env["record"].read_text())["env"]
    assert child["ANTHROPIC_BASE_URL"].endswith("/anthropic/seat")  # the whole session runs on seat


def test_auto_stays_governed_without_the_seat_login_or_when_the_workspace_forbids_it(launch_env, capsys):
    _seat(launch_env)
    assert cli.main(["--", "-p", "hi"]) == 0
    assert _profile(launch_env) == "governed"
    assert "→ this session: governed, model claude-opus-5-5 (auto: no seat login recorded)" in capsys.readouterr().err
    profile_choice.mark_seat_session_ok(launch_env["state"])
    _seat(launch_env, seat_mode="forbidden", reason="seat_classification_too_sensitive")
    assert cli.main(["--", "-p", "hi"]) == 0
    assert _profile(launch_env) == "governed"
    assert "(auto: Workspace forbids seat: seat_classification_too_sensitive)" in capsys.readouterr().err


def test_an_explicit_profile_keeps_todays_behaviour(launch_env, capsys):
    _seat(launch_env)
    profile_choice.mark_seat_session_ok(launch_env["state"])
    assert cli.main(["--profile", "governed", "--", "-p", "hi"]) == 0
    assert _profile(launch_env) == "governed" and "(--profile governed)\n" in capsys.readouterr().err
    _seat(launch_env, seat_mode="forbidden", reason="seat_mode_forbidden")
    assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 2
    assert "denied: seat_mode_forbidden (use the governed profile)" in capsys.readouterr().err


def test_only_a_seat_session_that_ended_normally_marks_the_seat_login(launch_env, monkeypatch):
    _seat(launch_env)
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "3")
    assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 3
    assert not profile_choice.seat_logged_in(launch_env["state"])
    assert cli.main(["--profile", "governed", "--", "-p", "hi"]) == 3
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "0")
    assert cli.main(["--profile", "governed", "--", "-p", "hi"]) == 0
    assert not profile_choice.seat_logged_in(launch_env["state"])  # a governed session proves nothing about seat
    assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 0
    assert profile_choice.seat_logged_in(launch_env["state"])


def test_a_codex_seat_login_alone_offers_the_seat_profile(state):
    """A device with only the person's ChatGPT login (``octryx codex login``) offers seat for Codex."""
    from octryx_claude import codex_seat

    assert not profile_choice.seat_logged_in(state)
    login = codex_seat.ensure_seat_home(state.root) / "auth.json"
    login.write_text("{}")
    os.chmod(login, 0)  # unreadable: presence only
    try:
        assert profile_choice.seat_logged_in(state)
    finally:
        os.chmod(login, 0o600)
