"""The status block printed at every start and by status, governance not set up, and the default model."""

from __future__ import annotations

import json
import time

import pytest

from octryx_claude import (
    cli,
    cli_account,
    cli_launch,
    cli_session,
    launch,
    profile_choice,
    seat_status,
    status_block,
    usage,
)
from octryx_claude.platform import PlatformResult
from octryx_claude.seat_status import SeatFailure
from tests.seat_status_support import KEY, _supervise_recording

from .test_seat_profile import _seat


def test_every_start_prints_the_status_block_before_claude_starts(launch_env, monkeypatch, capsys):
    launch_env["state"].write_config({"base_url": "https://octryx.example.test", "workspace_id": "ws-1",
                                      "workspace_name": "Acme Orders"})
    _seat(launch_env)
    profile_choice.mark_seat_session_ok(launch_env["state"])
    launch_env["usage"] = PlatformResult("ok", body={"state": "allowed", "limit_usd": 50, "spent_usd": 3.25,
                                                     "seat_allowance": {"five_hour_pct": 42.0, "seven_day_pct": 13}},
                                         status_code=200, state="allowed")
    seen = _supervise_recording(launch_env, monkeypatch, capsys)

    assert cli.main([]) == 0

    block = [line for line in seen["err_before_claude"].splitlines() if line.startswith("octryx-claude: ")][:7]
    assert block == [
        "octryx-claude: Workspace Acme Orders (ws-1)",
        "octryx-claude:   seat (your Claude subscription): ready",
        "octryx-claude:   governed (company model):        ready",
        "octryx-claude:   seat allowance:                  5h 42% · 7d 13%",
        "octryx-claude:   daily budget:                    3.25 / 50.00 USD today",
        "octryx-claude:   → this session: seat, model claude-opus-5-5 (auto: Workspace allows seat and the seat "
        "login is present)",
        "octryx-claude:   company models (/model):         not offered in seat sessions (subscription models only)",
    ]
    assert seen["env"]["OCTRYX_PROFILE"] == "seat"


def test_the_block_names_a_forbidden_seat_and_a_model_from_the_claude_args(launch_env, monkeypatch, capsys):
    _seat(launch_env, seat_mode="forbidden", reason="seat_classification_too_sensitive")
    seen = _supervise_recording(launch_env, monkeypatch, capsys)
    assert cli.main(["--", "--model", "claude-sonnet-5"]) == 0
    err = seen["err_before_claude"]
    assert "seat (your Claude subscription): not allowed by the Workspace (seat_classification_too_sensitive)" in err
    assert ("→ this session: governed, model claude-sonnet-5 (from --model) (auto: Workspace forbids seat: "
            "seat_classification_too_sensitive)") in err
    assert "seat login:" not in err  # pointless when the Workspace forbids seat


def test_governance_not_set_up_is_shown_and_nothing_starts(launch_env, capsys):
    launch_env["policy"] = PlatformResult("refused", status_code=409, state="needs_configuration",
                                          reason="policy_missing")
    assert cli.main(["--", "-p", "hi"]) == 2
    err = capsys.readouterr().err
    assert "governed (company model):        not set up (client policy needs_configuration/policy_missing)" in err
    assert "seat (your Claude subscription): unknown (client policy unavailable)" in err
    assert "→" not in err and not launch_env["record"].exists()


@pytest.mark.parametrize(("failure", "expected"), [
    (SeatFailure("login_expired", "authentication_failed", 1.0), "octryx-claude: seat: your Claude subscription login "
                                                                 "was rejected (authentication_failed)"),
    (SeatFailure("limit_reached", "rate_limit", 1.0), "octryx-claude: seat: your Claude subscription limit is "
                                                      "reached (rate_limit"),
])
def test_a_failed_seat_session_says_so_and_never_marks_the_login(launch_env, monkeypatch, capsys, failure, expected):
    _seat(launch_env)
    _supervise_recording(launch_env, monkeypatch, capsys, failure=failure)
    assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 0
    assert expected in capsys.readouterr().err
    assert not profile_choice.seat_logged_in(launch_env["state"])


def test_after_an_expired_login_auto_starts_governed_and_says_why(launch_env, monkeypatch, capsys):
    _seat(launch_env)
    profile_choice.mark_seat_session_ok(launch_env["state"])
    seat_status.record_failure(launch_env["state"], KEY,
                               SeatFailure("login_expired", "authentication_failed", time.time()))
    seen = _supervise_recording(launch_env, monkeypatch, capsys)
    assert cli.main(["--", "-p", "hi"]) == 0
    assert "seat (your Claude subscription): login expired (rejected at " in seen["err_before_claude"]
    assert "→ this session: governed, model claude-opus-5-5 (auto: seat login expired)" in seen["err_before_claude"]
    assert launch_env["bodies"]["/sessions/register"]["profile"] == "governed"


# --- 1: status -----------------------------------------------------------------------------------------------------

def test_status_shows_the_block_for_the_next_session(state, monkeypatch, capsys):
    state.write_config(
        {"base_url": "https://octryx.example.test", "workspace_id": "ws-1", "workspace_name": "Acme Orders"}
    )
    paths = []

    def control_plane(state_arg, context, method, path, *, http, timeout, body=None):
        paths.append((method, path))
        return PlatformResult("ok", body={"state": "allowed", "seat": {"seat_mode": "allowed"}},
                              status_code=200, state="allowed")

    for module in (cli_launch, cli_session, cli_account):
        monkeypatch.setattr(module, "call_control_plane", control_plane)
    monkeypatch.setattr(usage, "call_control_plane", control_plane)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert paths == [("GET", "/client-policy"), ("GET", "/daily-budget?workspace_id=ws-1")]
    assert "octryx-claude: Workspace Acme Orders (ws-1)\n" in out
    assert f"seat (your Claude subscription): {seat_status.NO_LOGIN_RECORDED}" in out
    assert "→ next session: governed, model claude-opus-5-5 (auto: no seat login recorded)" in out


def test_session_model():
    aliases = {"main": "claude-opus-5-5"}
    assert status_block.session_model([], aliases) == "claude-opus-5-5"
    assert status_block.session_model(["--model=claude-sonnet-5"], aliases) == "claude-sonnet-5 (from --model)"
    assert status_block.session_model(["--model", "bad value"], aliases) == "claude-opus-5-5"


# --- 4: the default model ------------------------------------------------------------------------------------------

def test_the_main_model_defaults_to_opus_5_5_and_small_fast_stays_sonnet(launch_env):
    assert launch.DEFAULT_ALIASES == {"main": "claude-opus-5-5", "opus": "claude-opus-5-5",
                                      "small_fast": "claude-sonnet-5"}
    assert cli.main(["--", "-p", "hi"]) == 0
    child = json.loads(launch_env["record"].read_text())["env"]
    assert child["ANTHROPIC_MODEL"] == child["CLAUDE_CODE_SUBAGENT_MODEL"] == "claude-opus-5-5"
    assert child["ANTHROPIC_SMALL_FAST_MODEL"] == child["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "claude-sonnet-5"
