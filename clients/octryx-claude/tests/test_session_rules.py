"""Seat live findings SL-1..SL-5: scopes, the verification notice, the friendly reminder, MCP allow, headless."""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from octryx_claude import cli, hooks, launch_settings, oauth, session_rules
from octryx_claude.platform import PlatformResult
from octryx_claude.tokens import store_token_response
from tests.hooks_support import KEY

from .conftest import BASE_URL

FRIENDLY = "3 unread board messages for you. Read them with board_read, then continue or stop."


def _without_board_scope(state) -> None:
    credentials = state.credentials()
    credentials["scopes"] = [scope for scope in oauth.SCOPES.split() if scope != "work:manage"]  # a narrower grant
    state.write_credentials(credentials)


# --- SL-1: the grant carries work:manage ----------------------------------------------------------------------------


def test_a_fresh_login_grant_contains_work_manage(state):
    assert "work:manage" in oauth.SCOPES.split()
    url = oauth.authorize_url(BASE_URL, client_id="c", redirect_uri="http://127.0.0.1:1/cb", challenge="x", state="s")
    assert "work:manage" in parse_qs(urlsplit(url).query)["scope"][0].split()
    oauth._save(state, BASE_URL, "c", "http://127.0.0.1:1/cb",
                {"access_token": "a", "refresh_token": "r", "expires_in": 60, "scope": oauth.SCOPES})
    assert "work:manage" in state.credentials()["scopes"]
    assert session_rules.can_read_board(state) and session_rules.missing_scopes(state) == []


def test_a_refresh_records_the_granted_scopes():
    credentials: dict = {"scopes": ["model:invoke"]}
    store_token_response(credentials, {"access_token": "a", "refresh_token": "r", "scope": "model:invoke work:manage"},
                         audience="aud", now=0)
    assert credentials["scopes"] == ["model:invoke", "work:manage"]
    store_token_response(credentials, {"access_token": "b", "refresh_token": "s"}, audience="aud", now=0)
    assert credentials["scopes"] == ["model:invoke", "work:manage"]  # an answer without a scope keeps the record


def test_a_login_without_work_manage_gets_a_clear_notice_at_every_start(state):
    _without_board_scope(state)
    first = session_rules.scope_notice(state)
    assert first.startswith("your login lacks work:manage; run octryx-claude login")
    assert session_rules.scope_notice(state) == first  # one line per start, not a one-off the user can miss
    assert not session_rules.can_read_board(state)


def test_the_launcher_says_it_at_every_start(launch_env, capsys):
    _without_board_scope(launch_env["state"])
    cli.main(["--", "-p", "hi"])
    first = capsys.readouterr().err
    cli.main(["--", "-p", "hi"])
    second = capsys.readouterr().err
    assert first.count("lacks work:manage") == 1 and second.count("lacks work:manage") == 1


def test_the_unread_reminder_needs_a_grant_that_can_read_the_board(state, monkeypatch, capsys):
    _without_board_scope(state)
    output = _stop(state, monkeypatch, capsys, {"state": "passed", "unread_for_me": 3})
    assert output == ""  # never "use board_read" when board_read would be refused


# --- SL-2: the verification notice once per session -----------------------------------------------------------------


def _stop(state, monkeypatch, capsys, body, *, mode="interactive") -> str:
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv(session_rules.ENV_SESSION_MODE, mode)
    answer = PlatformResult("ok", body=body, status_code=200, state=body.get("state", ""),
                            reason=body.get("reason", ""))
    monkeypatch.setattr(hooks, "call_control_plane", lambda *args, **kwargs: answer)
    stop = {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": False}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(stop).encode())))
    hooks.run_stop(state, httpx.Client())
    return capsys.readouterr().out


NOT_CONFIGURED = {"state": "needs_configuration", "reason": "verification_not_configured"}


def test_the_verification_notice_is_said_once_per_session(state, monkeypatch, capsys):
    first = _stop(state, monkeypatch, capsys, NOT_CONFIGURED)
    second = _stop(state, monkeypatch, capsys, NOT_CONFIGURED)
    assert "verification is not configured" in json.loads(first)["systemMessage"] and second == ""


def test_after_the_launchers_warning_no_stop_repeats_it(state, monkeypatch, capsys):
    session_rules.record_verification_notice(state, KEY, "needs_configuration")
    assert _stop(state, monkeypatch, capsys, NOT_CONFIGURED) == ""
    unreachable = _stop(state, monkeypatch, capsys, {"state": "weird"})  # another state is still said
    assert "unknown state" in json.loads(unreachable)["systemMessage"]


def test_the_launcher_records_its_verification_warning(launch_env, capsys):
    launch_env["policy"] = PlatformResult("ok", body={"state": "allowed", "verification": {
        "state": "needs_configuration"}}, status_code=200, state="allowed")
    cli.main(["--", "-p", "hi"])
    context, _ = launch_env["code_intelligence"]
    notice = launch_env["state"].session_dir(context.session_key) / session_rules.VERIFICATION_NOTICE_FILE
    assert json.loads(notice.read_text()) == {"state": "needs_configuration"}
    assert "verification gate needs_configuration" in capsys.readouterr().err


# --- SL-3: a friendly reminder --------------------------------------------------------------------------------------


def test_the_reminder_reads_as_a_friendly_note(state, monkeypatch, capsys):
    output = json.loads(_stop(state, monkeypatch, capsys, {"state": "passed", "unread_for_me": 3}))
    assert output == {"decision": "block", "reason": FRIENDLY}
    assert "error" not in FRIENDLY.lower() and "—" not in FRIENDLY


# --- SL-4: the launcher's own MCP tools are pre-allowed, nothing else -----------------------------------------------


def test_the_settings_pre_allow_exactly_the_octryx_mcp_server():
    settings = launch_settings.build_settings(shim=Path("/opt/octryx/bin/octryx-claude"), state_root=Path("/s"), env={},
                                     policy={"permissions": {"deny": [], "ask": []}}, base_url=BASE_URL)
    assert settings["permissions"]["allow"] == ["mcp__octryx-knowledge"]
    assert launch_settings.build_mcp_config(shim=Path("/x"), base_url=BASE_URL)["mcpServers"].keys() == {
        "octryx-knowledge"}


# --- SL-5: headless runs are never hijacked -------------------------------------------------------------------------


def test_a_headless_run_gets_the_reminder_as_information_only(state, monkeypatch, capsys):
    output = json.loads(_stop(state, monkeypatch, capsys, {"state": "passed", "unread_for_me": 3}, mode="headless"))
    assert output == {"systemMessage": FRIENDLY}
    nudges = {"state": "passed", "handoff_nudges": [{"work_item_key": "BRD-6", "marker": "c1:-:0", "kind": "update"}]}
    output = json.loads(_stop(state, monkeypatch, capsys, nudges, mode="headless"))
    assert "decision" not in output and output["systemMessage"].startswith("Update the handoff for BRD-6")


def test_the_verification_gate_still_blocks_a_headless_run(state, monkeypatch, capsys):
    blocked = {"state": "blocked", "detail": "Run the focused tests.", "unread_for_me": 2}
    output = json.loads(_stop(state, monkeypatch, capsys, blocked, mode="headless"))
    assert output["decision"] == "block" and output["reason"] == "Run the focused tests."
    assert "unread board messages" in output["systemMessage"]


def test_the_launcher_marks_print_runs_headless(launch_env):
    cli.main(["--", "-p", "hi"])
    headless = json.loads(launch_env["record"].read_text())["env"][session_rules.ENV_SESSION_MODE]
    cli.main(["--", "--model", "x"])
    interactive = json.loads(launch_env["record"].read_text())["env"][session_rules.ENV_SESSION_MODE]
    assert (headless, interactive) == ("headless", "interactive")
    assert session_rules.headless_session(["--print=json"]) and not session_rules.headless_session(["--prompt-x"])
