"""Root live two-agent E2E: resume checks out the WIP commit byte for byte, whatever the receiver's git config."""

from __future__ import annotations

import subprocess

import pytest

from octryx_claude.handoff_resume import run_resume
from tests.handoff_support import Platform, context, git, hand_over, repos  # noqa: F401 - the shared repos fixture

from .gitrepo import requires_git

pytestmark = requires_git


def _receiver_config(tmp_path, monkeypatch, kind: str = "autocrlf") -> None:
    attributes = tmp_path / "global-attributes"
    attributes.write_text("* text eol=crlf filter=shout\n")
    core = (f"\tautocrlf = true\n\tattributesFile = {attributes}\n" if kind == "autocrlf" else
            "\tautocrlf = false\n\teol = crlf\n")
    config = tmp_path / "receiver-gitconfig"
    config.write_text(f"[user]\n\tname = r\n\temail = r@example.test\n[core]\n{core}"
                      "[filter \"shout\"]\n\tsmudge = tr a-z A-Z\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


def _tracked_bytes(path) -> dict[str, bytes]:
    names = git(path, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    return {name: subprocess.run(["git", "cat-file", "blob", f"HEAD:{name}"], cwd=path, capture_output=True,
                                 check=True).stdout for name in names}


@pytest.mark.parametrize("push", ["branch", "bundle_only"])
@pytest.mark.parametrize("kind", ["autocrlf", "eol"])
def test_resume_is_byte_identical_under_a_converting_receiver_config(
        state, repos, tmp_path, monkeypatch, push, kind):  # noqa: F811 - repos is the shared fixture
    (repos["user"] / ".gitattributes").write_text("* text=auto\n")  # the repository's own: it still applies
    platform = Platform(push=push, repositories=[str(repos["remote"])])
    hand_over(state, platform, repos["user"])
    _receiver_config(tmp_path, monkeypatch, kind)
    with platform.client() as http:
        result = run_resume(state, context(), http, key="BRD-6", cwd=repos["receiver"])

    assert result.error == ""
    committed = _tracked_bytes(result.path)
    assert committed and all((result.path / name).read_bytes() == data for name, data in committed.items())
    assert (result.path / "src" / "app.py").read_bytes() == b"print('v2 work in progress')\n"
    assert git(result.path, "status", "--porcelain", "--untracked-files=no") == ""


@pytest.mark.parametrize("kind", ["autocrlf", "eol"])
def test_the_receivers_own_config_would_convert_without_the_fix(tmp_path, monkeypatch, repos, kind):  # noqa: F811
    (repos["receiver"] / ".gitattributes").write_text("* text=auto\n")
    git(repos["receiver"], "add", ".gitattributes")
    git(repos["receiver"], "commit", "-q", "-m", "attributes")
    _receiver_config(tmp_path, monkeypatch, kind)
    plain = tmp_path / "plain"
    git(repos["receiver"], "worktree", "add", "-q", "--detach", str(plain), "HEAD")
    assert (plain / "README.md").read_bytes() != b"# demo\n"
