"""``octryx-claude configure``: the installer stores the platform (and Workspace) without a login."""

from __future__ import annotations

import pytest

from octryx_claude import cli, cli_account, workspaces
from octryx_claude.state import LocalState
from octryx_claude.workspaces import Workspace

from .conftest import BASE_URL


@pytest.fixture
def fresh(tmp_path, monkeypatch) -> LocalState:
    root = tmp_path / "octryx"
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(root))
    return LocalState(root)


def test_configure_stores_base_url_and_workspace_request_without_secrets(fresh, capsys):
    assert cli.main(["configure", "--base-url", f"{BASE_URL}/", "--workspace", "Acme Orders"]) == 0
    assert fresh.config() == {"base_url": BASE_URL, "workspace_request": "Acme Orders"}
    assert not fresh.credentials_path.exists()
    capsys.readouterr()
    cli.main(["status"])
    out = capsys.readouterr().out
    assert f"base URL:   {BASE_URL}\n" in out
    assert "workspace:  Acme Orders (selected at the next login)" in out
    assert "not logged in" in out


def test_a_later_plain_login_uses_the_stored_platform_and_selects_the_requested_workspace(fresh, monkeypatch):
    seen = []
    monkeypatch.setattr(cli_account, "headless_login", lambda state, base_url, http: seen.append(base_url))
    monkeypatch.setattr(workspaces, "fetch_workspaces",
                        lambda state, http, base_url: [Workspace("ws-1", "Acme Orders")])
    assert cli.main(["configure", "--base-url", BASE_URL, "--workspace", "acme orders"]) == 0
    assert cli.main(["login", "--headless"]) == 0
    assert seen == [BASE_URL]
    assert fresh.config() == {"base_url": BASE_URL, "workspace_id": "ws-1", "workspace_name": "Acme Orders"}


def test_another_platform_drops_the_old_workspace_selection(fresh):
    fresh.write_config({"base_url": "https://old.example.test", "workspace_id": "ws-9", "workspace_name": "Old",
                        "aliases": {"main": "m"}})
    assert cli.main(["configure", "--base-url", BASE_URL]) == 0
    assert fresh.config() == {"base_url": BASE_URL, "aliases": {"main": "m"}}
    fresh.write_config({"base_url": BASE_URL, "workspace_id": "ws-1"})
    assert cli.main(["configure", "--base-url", BASE_URL]) == 0  # the same platform keeps the selection
    assert fresh.config()["workspace_id"] == "ws-1"


@pytest.mark.parametrize("args", [
    ["--base-url", "ftp://octryx.example.test"],
    ["--base-url", "https://user:secret@octryx.example.test"],
    ["--base-url", "https://octryx.example.test/?token=x"],
    ["--base-url", BASE_URL, "--workspace", "bad\nvalue"],
])
def test_unusable_values_are_refused_and_nothing_is_stored(fresh, args, capsys):
    assert cli.main(["configure", *args]) == 2
    assert fresh.config() == {}
    assert "secret" not in capsys.readouterr().err
