"""Login scopes (SL-1 follow-up): the login records its grant, the start names a missing scope, and
``analyze`` refuses up front instead of failing at submit with HTTP 403. A login without a grant record lacks every
requested scope until the next login or refresh records it.
"""

from __future__ import annotations

import time

from octryx_claude import cli, oauth, profile_choice, session_rules
from octryx_claude.platform import PlatformResult
from octryx_claude.tokens import GATEWAY_AUDIENCE

from .conftest import BASE_URL

LACKS = "your login lacks work:manage; run octryx-claude login"
PARTIAL_SCOPES = ("model:invoke knowledge:read knowledge:write session:write workflow:read workflow:execute "
                  "sessions:read")


def _set_scopes(state, scopes: list[str] | None) -> None:
    credentials = state.credentials()
    if scopes is None:
        credentials.pop("scopes", None)  # a login without a grant record
    else:
        credentials["scopes"] = scopes
    state.write_credentials(credentials)


def _seat_ready(launch_env) -> None:
    launch_env["policy"] = PlatformResult("ok", body={"state": "allowed", "seat": {"seat_mode": "allowed"}},
                                          status_code=200, state="allowed")
    launch_env["register"] = PlatformResult(
        "ok", body={"state": "registered", "profile": "seat", "purpose": "work_item_analysis",
                    "seat_credential": "s3at-" + "x" * 40, "credential_header": "X-Octryx-Seat-Credential"},
        status_code=200, state="registered")
    profile_choice.mark_seat_session_ok(launch_env["state"])


# --- login records the grant ----------------------------------------------------------------------------------------


def test_the_login_stores_exactly_the_granted_scopes(state):
    oauth._save(state, BASE_URL, "c", "http://127.0.0.1:1/cb",
                {"access_token": "a", "refresh_token": "r", "expires_in": 60, "scope": PARTIAL_SCOPES})
    assert state.credentials()["scopes"] == sorted(PARTIAL_SCOPES.split())  # what was granted, not what was requested
    assert session_rules.missing_scopes(state) == ["work:manage"]


# --- start notice ---------------------------------------------------------------------------------------------------


def test_the_start_notice_names_a_missing_scope(launch_env, capsys):
    _set_scopes(launch_env["state"], sorted(PARTIAL_SCOPES.split()))
    assert cli.main(["--", "-p", "hi"]) == 0
    assert f"octryx-claude: {LACKS}" in capsys.readouterr().err


def test_the_start_notice_names_every_missing_requested_scope(state):
    _set_scopes(state, ["model:invoke", "knowledge:read", "knowledge:write", "session:write", "sessions:read"])
    assert session_rules.scope_notice(state).startswith(
        "your login lacks workflow:read, workflow:execute, work:manage; run octryx-claude login")


def test_no_start_notice_when_the_login_has_every_scope(launch_env, capsys):
    assert cli.main(["--", "-p", "hi"]) == 0
    assert "lacks" not in capsys.readouterr().err
    assert session_rules.scope_notice(launch_env["state"]) == ""


# --- analyze refuses up front ---------------------------------------------------------------------------------------


def test_analyze_refuses_up_front_without_work_manage(launch_env, capsys):
    _seat_ready(launch_env)
    _set_scopes(launch_env["state"], sorted(PARTIAL_SCOPES.split()))
    assert cli.main(["analyze", "INC0000103"]) == 2
    assert launch_env["steps"] == [] and not launch_env["record"].exists()  # no platform call, no session
    assert f"octryx-claude: analysis not started: {LACKS}\n" in capsys.readouterr().err


def test_analyze_starts_when_the_login_has_its_scopes(launch_env, capsys):
    _seat_ready(launch_env)
    _set_scopes(launch_env["state"], ["knowledge:read", "model:invoke", "work:manage"])
    assert cli.main(["analyze", "INC0000103"]) == 0
    err = capsys.readouterr().err
    # The start still names the other requested scopes; analyze itself needs only these two.
    assert "/sessions/register" in launch_env["steps"] and "analysis not started" not in err
    assert "work:manage" not in err and "knowledge:read" not in err


# --- a login without a grant record -------------------------------------------------------------------------------


def test_a_login_without_a_grant_record_lacks_every_requested_scope(state):
    _set_scopes(state, None)
    assert session_rules.granted_scopes(state) is None
    assert session_rules.missing_scopes(state) == list(session_rules.requested_scopes())
    assert session_rules.analyze_scope_refusal(state) == (
        "your login lacks knowledge:read, work:manage; run octryx-claude login")


def test_a_login_without_a_grant_record_cannot_start_analyze(launch_env, capsys):
    _seat_ready(launch_env)
    _set_scopes(launch_env["state"], None)
    assert cli.main(["analyze", "INC0000103"]) == 2
    assert launch_env["steps"] == []
    assert "analysis not started: your login lacks knowledge:read, work:manage" in capsys.readouterr().err


def test_the_next_refresh_records_the_grant(state):
    _set_scopes(state, None)
    credentials = state.credentials()
    credentials["tokens"] = {GATEWAY_AUDIENCE: {"access_token": "old", "expires_at": time.time() - 1}}
    state.write_credentials(credentials)

    class _Http:
        def post(self, *_args, **_kwargs):
            class _Response:
                status_code = 200

                def json(self):
                    return {"access_token": "new", "refresh_token": "r2", "expires_in": 3600, "scope": PARTIAL_SCOPES}
            return _Response()

    from octryx_claude.tokens import get_access_token

    assert get_access_token(state, GATEWAY_AUDIENCE, http=_Http()) == "new"
    assert session_rules.granted_scopes(state) == frozenset(PARTIAL_SCOPES.split())
    assert session_rules.missing_scopes(state) == ["work:manage"]


def test_without_a_login_no_scope_is_claimed_missing(state):
    state.write_credentials({})
    assert session_rules.missing_scopes(state) == [] and session_rules.analyze_scope_refusal(state) == ""
