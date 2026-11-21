"""``--workspace`` takes an id or a name (owner: ``octryx-claude --workspace "Acme Orders"``)."""

from __future__ import annotations

import httpx
import pytest

from octryx_claude import cli, cli_account, workspaces
from octryx_claude.workspaces import Workspace, WorkspaceError, resolve_workspace

from .conftest import BASE_URL

MINE = [Workspace("ws-1", "Acme Orders"), Workspace("ws-2", "Alpha"), Workspace("ws-3", "alpha")]


@pytest.mark.parametrize(("value", "expected"), [
    ("ws-1", "ws-1"), ("Acme Orders", "ws-1"), ("acme orders", "ws-1"), ("  ACME ORDERS ", "ws-1"), ("ws-2", "ws-2"),
])
def test_an_id_or_a_case_insensitive_exact_name_resolves(value, expected):
    assert resolve_workspace(value, MINE).id == expected


def test_an_ambiguous_name_asks_for_the_id():
    with pytest.raises(WorkspaceError) as error:
        resolve_workspace("ALPHA", MINE)
    message = str(error.value)
    assert "ambiguous" in message and "Alpha (ws-2)" in message and "alpha (ws-3)" in message
    assert "Acme Orders" not in message


def test_an_unknown_name_lists_the_usable_workspaces():
    for value in ("Acme", "Acme Orders2", "ws-9"):  # no prefix or partial matching
        with pytest.raises(WorkspaceError) as error:
            resolve_workspace(value, MINE)
        assert "unknown Workspace" in str(error.value) and "Acme Orders (ws-1), Alpha (ws-2), alpha (ws-3)" in str(
            error.value)


def test_without_an_answer_an_id_still_works_and_a_name_is_refused():
    assert resolve_workspace("ws-7", None) == Workspace("ws-7")
    with pytest.raises(WorkspaceError) as error:
        resolve_workspace("Acme Orders", None)
    assert "pass the Workspace id" in str(error.value)
    with pytest.raises(WorkspaceError):
        resolve_workspace("  ", MINE)


def test_the_list_comes_from_the_gateway_with_the_launchers_login(state):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [{"id": "ws-1", "name": "Acme Orders"}, {"name": "no id"},
                                                   {"id": "bad id\n", "name": "x"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        listed = workspaces.fetch_workspaces(state, http, BASE_URL)
    assert listed == [Workspace("ws-1", "Acme Orders")]
    assert seen[0].url.path == "/api/v1/agent-gateway/workspaces"
    assert seen[0].headers["authorization"] == "Bearer gw-cached"
    refused = httpx.Response(403, json={"items": [{"id": "ws-1", "name": "Acme Orders"}]})  # never read on a refusal
    with httpx.Client(transport=httpx.MockTransport(lambda request: refused)) as http:
        assert workspaces.fetch_workspaces(state, http, BASE_URL) is None


def test_the_launcher_starts_in_a_workspace_given_by_name(launch_env, monkeypatch, capsys):
    monkeypatch.setattr(workspaces, "fetch_workspaces", lambda state, http, base_url: MINE)
    cli.main(["--workspace", "acme orders", "--", "-p", "hi"])
    context, _ = launch_env["code_intelligence"]
    assert context.workspace_id == "ws-1"
    assert "workspace Acme Orders (ws-1) |" in capsys.readouterr().err
    assert cli.main(["--workspace", "nope", "--", "-p", "hi"]) == 2
    assert "unknown Workspace 'nope'; your Workspaces: Acme Orders (ws-1)" in capsys.readouterr().err


def test_login_stores_the_resolved_id_and_status_shows_name_and_id(state, monkeypatch, capsys):
    monkeypatch.setattr(cli_account, "headless_login", lambda state, base_url, http: None)
    monkeypatch.setattr(workspaces, "fetch_workspaces", lambda state, http, base_url: MINE)
    assert cli.main(["login", "--base-url", BASE_URL, "--workspace", "ACME ORDERS", "--headless"]) == 0
    config = state.config()
    assert (config["workspace_id"], config["workspace_name"]) == ("ws-1", "Acme Orders")
    assert "Workspace: Acme Orders (ws-1)." in capsys.readouterr().out
    cli.main(["status"])
    assert "workspace:  Acme Orders (ws-1)" in capsys.readouterr().out
    assert cli.main(["login", "--base-url", BASE_URL, "--workspace", "alpha", "--headless"]) == 2
    assert state.config()["workspace_id"] == "ws-1"  # an ambiguous name never changes the selection
    assert "ambiguous" in capsys.readouterr().err


def test_a_stored_id_without_a_name_still_shows_the_id(state, capsys):
    state.write_config({"base_url": BASE_URL, "workspace_id": "ws-5"})
    cli.main(["status"])
    assert "workspace:  ws-5\n" in capsys.readouterr().out
    assert workspaces.label_for({"workspace_id": "ws-1", "workspace_name": "Acme Orders"}, "ws-2") == "ws-2"
