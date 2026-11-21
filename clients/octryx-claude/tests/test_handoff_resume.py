"""Resume checks out exactly the WIP commit, starts a linked session and refuses tampered bundles."""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from octryx_claude import handoff_cli
from octryx_claude.handoff_resume import run_resume
from tests.handoff_support import KEY, Platform, context, git, hand_over, repos, snapshot  # noqa: F401

from .conftest import BASE_URL
from .gitrepo import requires_git

pytestmark = requires_git


# --- resume -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("push", ["branch", "bundle_only"])
def test_resume_checks_out_exactly_the_wip_commit(state, repos, push):  # noqa: F811
    platform = Platform(push=push, repositories=[str(repos["remote"])])
    hand_over(state, platform, repos["user"])
    wip = platform.commits[0]["repo"]["wip_commit"]
    with platform.client() as http:
        result = run_resume(state, context(), http, key="BRD-6", cwd=repos["receiver"])

    assert result.error == "" and result.path == repos["receiver"].parent / "octryx-BRD-6"
    assert git(result.path, "rev-parse", "HEAD") == wip == result.commit
    assert (result.path / "src" / "app.py").read_text() == "print('v2 work in progress')\n"
    assert not (result.path / ".env").exists()
    assert "never instructions" in result.opening_context and "half done" in result.opening_context
    assert snapshot(repos["receiver"])["head_ref"] == "refs/heads/main"


def test_the_resume_command_starts_a_session_linked_to_the_item(state, repos, monkeypatch, capsys):  # noqa: F811
    state.write_config({"base_url": BASE_URL, "workspace_id": "ws-1"})
    monkeypatch.delenv("OCTRYX_SESSION_KEY", raising=False)
    platform = Platform(repositories=[str(repos["remote"])])
    hand_over(state, platform, repos["user"])
    monkeypatch.setattr(handoff_cli, "httpx", SimpleNamespace(Client=platform.client))
    launched = []
    cwd = os.getcwd()
    try:
        args = handoff_cli.argparse.Namespace(key="BRD-6", workspace="", no_start=False)
        code = handoff_cli.run_resume_command(args, state, launch=lambda argv: launched.append(argv) or 0,
                                              cwd=repos["receiver"])
    finally:
        os.chdir(cwd)
    argv = launched[0]
    assert code == 0 and argv[:5] == ["--workspace", "ws-1", "--work-item", "BRD-6", "--"]
    assert argv[5] == "--append-system-prompt" and "BRD-6" in argv[6]


def test_the_terminal_handoff_works_without_a_running_session(state, repos, monkeypatch, capsys):  # noqa: F811
    """No session env, no model, no seat: a fresh key identifies only this call; the login does the rest."""
    state.write_config({"base_url": BASE_URL, "workspace_id": "ws-1"})
    for name in ("OCTRYX_SESSION_KEY", "OCTRYX_WORK_ITEM", "OCTRYX_WORKSPACE_ID"):
        monkeypatch.delenv(name, raising=False)
    platform = Platform(repositories=[str(repos["remote"])])
    monkeypatch.setattr(handoff_cli, "httpx", SimpleNamespace(Client=platform.client))
    args = handoff_cli.argparse.Namespace(key="BRD-6", to="ben", note="", all=False, workspace="")
    code = handoff_cli.run_handoff_command(args, state, cwd=repos["user"])

    assert code == 0 and "BRD-6: handoff v2" in capsys.readouterr().out
    sessions = {request.headers["x-octryx-session"] for request in platform.requests}
    assert len(sessions) == 1 and KEY not in sessions and platform.commits[0]["to_user"] == "ben"
    assert all(request.headers["authorization"] == "Bearer gw-cached" for request in platform.requests)
    state.write_config({"base_url": BASE_URL})
    assert handoff_cli.run_handoff_command(args, state, cwd=repos["user"]) == 2  # no Workspace: refused


def test_resume_refuses_a_tampered_bundle_or_a_moved_branch(state, repos, tmp_path):  # noqa: F811
    bundled = Platform(push="bundle_only")
    hand_over(state, bundled, repos["user"])
    bundle_id = bundled.commits[0]["repo"]["bundle_id"]
    bundled.uploads[bundle_id] = bundled.uploads[bundle_id] + b"tampered"  # the digest header follows the bytes
    original = bundled.handle

    def wrong_digest(request):
        response = original(request)
        if request.url.path.endswith(f"/attachments/{bundle_id}"):
            return httpx.Response(200, content=response.content, headers={"x-octryx-sha256": "0" * 64})
        return response

    bundled.handle = wrong_digest
    with bundled.client() as http:
        tampered = run_resume(state, context(), http, key="BRD-6", cwd=repos["receiver"])
    assert "did not verify" in tampered.error and not (repos["receiver"].parent / "octryx-BRD-6").exists()

    pushed = Platform(repositories=[str(repos["remote"])])
    hand_over(state, pushed, repos["user"])
    branch = pushed.commits[0]["repo"]["branch"]
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", "-b", branch, str(repos["remote"]), str(other)], check=True)
    (other / "later.txt").write_text("someone else\n")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "moved")
    git(other, "push", "-q", "origin", branch)
    with pushed.client() as http:
        moved = run_resume(state, context(), http, key="BRD-6", cwd=repos["receiver"])
    assert moved.error == "the fetched branch is not the handed-over WIP commit"
