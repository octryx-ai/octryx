"""``octryx-claude analyze <KEY>``: a work item analysis in a seat session.

The fake control plane and the fake claude of ``conftest.launch_env``; no network, no model.
"""

from __future__ import annotations

import json

from octryx_claude import analyze_cli, cli, profile_choice
from octryx_claude.platform import PlatformResult

CREDENTIAL = "s3at-Cred_" + "x" * 40


def _seat(launch_env, *, seat_mode: str = "allowed", reason: str | None = None, logged_in: bool = True) -> None:
    launch_env["policy"] = PlatformResult("ok", body={"state": "allowed", "seat": {"seat_mode": seat_mode,
                                                                                   "reason": reason}},
                                          status_code=200, state="allowed")
    launch_env["register"] = PlatformResult(
        "ok", body={"state": "registered", "profile": "seat", "purpose": "work_item_analysis",
                    "seat_credential": CREDENTIAL, "credential_header": "X-Octryx-Seat-Credential"},
        status_code=200, state="registered")
    if logged_in:
        profile_choice.mark_seat_session_ok(launch_env["state"])


def test_analyze_starts_a_pinned_headless_seat_session_with_only_the_analysis_tools(launch_env, capsys):
    _seat(launch_env)

    assert cli.main(["analyze", "INC0000103"]) == 0

    assert launch_env["steps"][:4] == ["/client-policy", "/sessions/register", "/skills/manifest", "/sessions/hook-key"]
    assert launch_env["bodies"]["/sessions/register"]["profile"] == "seat"
    assert launch_env["bodies"]["/sessions/register"]["purpose"] == "work_item_analysis"
    child = json.loads(launch_env["record"].read_text())
    assert child["env"]["OCTRYX_WORK_ITEM"] == "INC0000103"
    assert "X-Octryx-Work-Item: INC0000103" in child["env"]["ANTHROPIC_CUSTOM_HEADERS"]
    argv = child["argv"]
    assert argv[argv.index("-p") + 1].startswith("Analyse the work item INC0000103.")
    assert "work_item_analysis_submit" in argv[argv.index("--append-system-prompt") + 1]
    disallowed = argv[argv.index("--disallowedTools") + 1:]
    assert {"Bash", "Read", "Edit", "Write", "WebFetch"} <= set(disallowed)
    assert "code_intelligence" not in launch_env["steps"]  # no repository is bound for an analysis
    assert CREDENTIAL not in capsys.readouterr().err


def test_analyze_refuses_before_registration_when_the_seat_is_not_ready(launch_env, capsys):
    _seat(launch_env, logged_in=False)
    assert cli.main(["analyze", "INC0000103"]) == 2
    assert launch_env["steps"] == ["/client-policy"] and not launch_env["record"].exists()
    assert "analysis not started: needs_configuration: seat_not_logged_in (run: octryx-claude login --seat)" in \
        capsys.readouterr().err


def test_analyze_refuses_when_the_workspace_forbids_seat(launch_env, capsys):
    _seat(launch_env, seat_mode="forbidden", reason="seat_classification_too_sensitive")
    assert cli.main(["analyze", "INC0000103"]) == 2
    assert launch_env["steps"] == ["/client-policy"]
    assert "denied: seat_classification_too_sensitive" in capsys.readouterr().err


def test_a_refused_analysis_registration_says_why(launch_env, capsys):
    _seat(launch_env)
    launch_env["register"] = PlatformResult("refused", status_code=403, state="denied",
                                            reason="analysis_runner_not_seat")
    assert cli.main(["analyze", "INC0000103"]) == 2
    assert not launch_env["record"].exists()
    assert "registration denied/analysis_runner_not_seat" in capsys.readouterr().err


def test_an_unsafe_key_is_refused_without_any_call(launch_env, capsys):
    # "INC/0001" would pass as a header value; a work item key in a command line is stricter.
    for key in ("INC 1; rm -rf /", "INC/0001", "INC:1"):
        assert cli.main(["analyze", key]) == 2
    assert launch_env["steps"] == []
    assert "denied: work_item_invalid" in capsys.readouterr().err


def test_seat_states_map_to_their_fix():
    from octryx_claude.seat_status import SeatState

    assert analyze_cli.seat_not_ready(SeatState("ready", "ready")) == ""
    assert "run: octryx-claude login --seat" in analyze_cli.seat_not_ready(SeatState("login_expired", "x"))
    assert analyze_cli.seat_not_ready(SeatState("limit_reached", "limit reached")) == \
        "needs_configuration: seat_limit_reached (limit reached)"
    assert analyze_cli.seat_not_ready(SeatState("unknown", "unknown")).startswith("needs_configuration: seat_unknown")
