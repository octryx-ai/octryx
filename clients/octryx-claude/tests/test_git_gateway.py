"""A server runner fetches the run's branch through the platform (``git_gateway``) with the token only in that
git call's environment; ``origin`` keeps its URL, and a device keeps fetching from origin."""

from __future__ import annotations

import json

import httpx
import pytest

from octryx_claude import git_gateway, platform, workspace_branch, workspace_prep
from octryx_claude.platform import SessionContext
from tests.gitrepo import git, requires_git
from tests.workspace_prep_support import BRANCH, _origin

PATH = "/api/v1/agent-gateway/git/run-1"
CONTEXT = SessionContext("http://platform.test", "7b0c6d1e-1f2a-4b3c-8d4e-5f6a7b8c9d0e", "ws-1", "", "run-1")


def test_the_token_goes_to_the_gateway_url_only_and_after_the_configuration_already_there():
    env = git_gateway.fetch_env("http://gw:8000/git/r", "tok", base={"GIT_CONFIG_COUNT": "2"})
    assert env == {"GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_2": "http.http://gw:8000/git/r.extraHeader",
                   "GIT_CONFIG_VALUE_2": "Authorization: Bearer tok"}


@requires_git
def test_a_runner_fetches_the_branch_through_the_platform_and_never_asks_origin(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    platform_copy = tmp_path / "origin.git"  # stands in for the platform's git URL
    unreachable = "http://127.0.0.1:9/never-asked.git"
    git(folder, "remote", "set-url", "origin", unreachable)
    asked: list[str] = []

    def gateway():
        asked.append("token")
        return str(platform_copy), {"GIT_CONFIG_COUNT": "0"}

    report = workspace_branch.prepare_branch(folder, BRANCH, gateway=gateway)
    assert report["state"] == "checked_out", report
    assert asked == ["token"]
    assert git(folder, "rev-parse", "HEAD") == git(platform_copy, "rev-parse", f"refs/heads/{BRANCH}")
    assert git(folder, "config", "--get", "remote.origin.url") == unreachable  # origin itself is unchanged
    assert "extraHeader" not in (folder / ".git" / "config").read_text()

    # The platform refuses the token: the folder stays as it is, nothing else is tried.
    git(folder, "checkout", "-q", "main")
    git(folder, "branch", "-D", BRANCH)
    git(folder, "update-ref", "-d", f"refs/remotes/origin/{BRANCH}")
    refused = workspace_branch.prepare_branch(folder, BRANCH, gateway=lambda: None)
    assert refused["state"] == "unavailable" and git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_the_token_comes_from_the_session_for_the_offered_path_only(monkeypatch):
    monkeypatch.setattr(platform, "get_access_token", lambda *args, **kwargs: "gateway-login")
    seen: list[httpx.Request] = []
    answer = {"state": "ready", "token": "run-bound", "path": PATH}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=answer)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        url, env = git_gateway.source_for(None, CONTEXT, PATH, http=http)()
        assert url == f"http://platform.test{PATH}" and "Authorization: Bearer run-bound" in env.values()
        assert seen[0].url.path == "/api/v1/agent-gateway/sessions/git-token"
        assert seen[0].headers["x-octryx-session"] == CONTEXT.session_key
        answer["path"] = "/api/v1/agent-gateway/git/another-run"
        assert git_gateway.source_for(None, CONTEXT, PATH, http=http)() is None


@pytest.mark.parametrize("runner", [True, False])
def test_only_a_runner_uses_the_gateway_the_run_offers(monkeypatch, runner):
    from octryx_claude import codex_config

    monkeypatch.setattr(codex_config, "agent_mode", lambda: runner)
    contract = {"preparation": {"branch": BRANCH, "git_gateway": PATH}}
    chosen = workspace_prep._gateway(None, CONTEXT, contract, http=None)
    assert (chosen is not None) is runner
    assert workspace_prep._gateway(None, CONTEXT, json.loads('{"preparation": {"branch": "b"}}'), http=None) is None


def test_the_agent_may_use_git_in_the_job_folder_the_launcher_set_up(monkeypatch, tmp_path):
    from octryx_claude import runner

    monkeypatch.delenv(runner.AGENT_UID_ENV, raising=False)
    assert runner.agent_git_env(str(tmp_path)) == {}  # a device: nothing changes
    monkeypatch.setenv(runner.AGENT_UID_ENV, "10002")
    env = runner.agent_git_env(str(tmp_path), {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.pager",
                                               "GIT_CONFIG_VALUE_0": "cat"})
    assert env == {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "core.pager", "GIT_CONFIG_VALUE_0": "cat",
                   "GIT_CONFIG_KEY_1": "safe.directory", "GIT_CONFIG_VALUE_1": str(tmp_path.resolve())}
