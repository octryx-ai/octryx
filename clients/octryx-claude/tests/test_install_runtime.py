"""The installed-package runtime: shim resolution, console entry, update notice, logout."""

from __future__ import annotations

import io

import httpx
import pytest

from octryx_claude import entry, install_layout, logout, update_check
from octryx_claude.state import LocalState

from .conftest import BASE_URL

# --- install_layout ---------------------------------------------------------------------------


def test_checkout_shim_wins(tmp_path):
    checkout = tmp_path / "kit" / "bin" / "octryx-claude"
    checkout.parent.mkdir(parents=True)
    checkout.write_text("#!/bin/sh\n")
    assert install_layout.launcher_shim(checkout_shim=checkout, executable="/venv/bin/python") == checkout


def test_installed_copy_calls_the_versioned_venv_script(tmp_path):
    version_bin = tmp_path / "venvs" / "0.2.0+abc" / "bin"
    version_bin.mkdir(parents=True)
    (tmp_path / "venvs" / "current").symlink_to("0.2.0+abc")
    shim = install_layout.launcher_shim(checkout_shim=tmp_path / "missing",
                                        executable=str(tmp_path / "venvs" / "current" / "bin" / "python"))
    assert shim == version_bin.resolve() / "octryx-claude"


def test_checkout_has_no_installed_version():
    assert install_layout.installed_version() == ""


# --- entry ------------------------------------------------------------------------------------


def test_native_windows_is_refused_before_anything_runs(monkeypatch, capsys):
    monkeypatch.setattr(entry, "native_windows", lambda: True)
    assert entry.main(["status"]) == 2
    assert "native_windows_unsupported" in capsys.readouterr().err


def test_native_windows_detection():
    assert entry.native_windows("nt") is True
    assert entry.native_windows("posix") is False


@pytest.mark.parametrize(("argv", "expected"), [
    ([], True), (["status"], True), (["--profile", "seat"], True),
    (["api-key-helper"], False), (["mcp-headers"], False), (["hook", "pre-tool-use"], False),
])
def test_update_notice_only_for_person_facing_commands(argv, expected):
    assert entry.wants_update_notice(argv) is expected


def test_entry_dispatches_to_cli_after_the_update_step(monkeypatch):
    from octryx_claude import cli, self_update

    seen = []
    monkeypatch.setattr(entry, "native_windows", lambda: False)
    monkeypatch.setattr(self_update, "on_start", lambda argv, out: seen.append("notice"))
    monkeypatch.setattr(cli, "main", lambda args: seen.append(("cli", args)) or 7)
    assert entry.main(["hook", "stop"]) == 7
    assert seen == [("cli", ["hook", "stop"])]
    assert entry.main(["status"]) == 7
    assert seen[-2:] == ["notice", ("cli", ["status"])]


# --- update_check -----------------------------------------------------------------------------


def _http(answer: httpx.Response | Exception) -> tuple[httpx.Client, list]:
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if isinstance(answer, Exception):
            raise answer
        return answer

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def _configured(tmp_path) -> LocalState:
    state = LocalState(tmp_path / "s").ensure()
    state.write_config({"base_url": BASE_URL})
    return state


def test_notice_names_the_update_command(tmp_path):
    state = _configured(tmp_path)
    http, calls = _http(httpx.Response(200, json={"version": "0.3.0+def"}))
    out = io.StringIO()
    update_check.notify(out, state=state, now=1_000_000, http=http, installed="0.2.0+abc")
    assert calls == [f"{BASE_URL}/octryx-claude/version"]
    assert out.getvalue() == (f"octryx-claude: update available (0.2.0+abc -> 0.3.0+def); run: "
                              f"curl -fsSL '{BASE_URL}/octryx-claude/install.sh' | bash -s -- update\n")


def test_same_version_is_silent(tmp_path):
    http, _ = _http(httpx.Response(200, json={"version": "0.2.0+abc"}))
    out = io.StringIO()
    update_check.notify(out, state=_configured(tmp_path), now=1_000_000, http=http, installed="0.2.0+abc")
    assert out.getvalue() == ""


def test_checks_at_most_once_per_interval(tmp_path):
    state = _configured(tmp_path)
    http, calls = _http(httpx.Response(200, json={"version": "0.3.0"}))
    for moment in (1_000_000, 1_000_000 + update_check.CHECK_INTERVAL_SECONDS - 1):
        update_check.notify(io.StringIO(), state=state, now=moment, http=http, installed="0.2.0")
    assert len(calls) == 1
    update_check.notify(io.StringIO(), state=state, now=1_000_000 + update_check.CHECK_INTERVAL_SECONDS,
                        http=http, installed="0.2.0")
    assert len(calls) == 2


@pytest.mark.parametrize("answer", [
    httpx.ConnectError("offline"),
    httpx.Response(503, json={"version": "9.9.9"}),
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"version": "1.0; rm -rf /"}),
    httpx.Response(200, json=["0.3.0"]),
])
def test_failures_are_silent(tmp_path, answer):
    http, _ = _http(answer)
    out = io.StringIO()
    update_check.notify(out, state=_configured(tmp_path), now=1_000_000, http=http, installed="0.2.0")
    assert out.getvalue() == ""


def test_checkout_or_missing_login_never_checks(tmp_path):
    http, calls = _http(httpx.Response(200, json={"version": "0.3.0"}))
    update_check.notify(io.StringIO(), state=_configured(tmp_path), now=1, http=http, installed="")
    update_check.notify(io.StringIO(), state=LocalState(tmp_path / "empty").ensure(), now=1, http=http,
                        installed="0.2.0")
    assert calls == []


# --- logout -----------------------------------------------------------------------------------


def test_logout_revokes_the_refresh_token_and_removes_credentials(state):
    seen = []

    def handler(request):
        seen.append((str(request.url), request.content.decode()))
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert logout.logout(state, http) == "revoked"
    assert seen[0][0] == f"{BASE_URL}/oauth/revoke"
    assert "token=refresh-1" in seen[0][1] and "client_id=oec_test" in seen[0][1]
    assert not state.credentials_path.exists()


def test_logout_removes_credentials_even_when_revoke_fails(state):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as http:
        assert logout.logout(state, http) == "revoke_failed"
    assert not state.credentials_path.exists()


def test_logout_without_login(tmp_path):
    empty = LocalState(tmp_path / "e").ensure()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as http:
        assert logout.logout(empty, http) == "not_logged_in"


def test_logout_main_exit_codes(state, monkeypatch, capsys):
    monkeypatch.setattr(logout, "logout", lambda state_arg, http: "revoke_failed")
    assert logout.main() == 1
    assert "revoke_failed" in capsys.readouterr().err
