"""A failed git step names its class and git's last line without secrets; a transient one is tried again; the
platform's own disk is the environment's; the askpass script is one file per provider (a bare "git clone failed",
"git push failed" or "git pull failed" says nothing more)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from app.tools.connectors import git_errors
from app.tools.connectors.git_errors import classify, git_failure, last_line, run_with_retry

TOKEN = "ghp_" + "A" * 36


@pytest.mark.parametrize(("stderr", "kind"), [
    ("fatal: Authentication failed for 'https://github.com/o/r.git/'", "auth"),
    ("fatal: unable to access 'https://github.com/o/r.git/': Could not resolve host: github.com", "network"),
    ("remote: API rate limit exceeded\nfatal: unable to access '...': The requested URL returned error: 429",
     "rate_limit"),
    ("fatal: unable to access '...': The requested URL returned error: 503", "server_error"),
    ("fatal: could not create work tree dir 'r': No space left on device", "disk"),
    ("error: unable to create temporary file: Read-only file system", "disk"),
    ("remote: Repository not found.\nfatal: repository 'https://github.com/o/r.git/' not found", "not_found"),
    ("fatal: Not possible to fast-forward, aborting.", "non_fast_forward"),
])
def test_each_failure_names_its_class(stderr, kind):
    assert classify(stderr) == kind
    failure = git_failure("git clone failed", 128, stderr)
    assert failure["error_class"] == kind and failure["error"].startswith("git clone failed: ")
    assert failure["error_code"] == "git_clone_failed" and failure["git_said"]  # the code stays


def test_git_s_last_line_never_carries_a_credential():
    said = last_line(f"Cloning into 'r'...\nfatal: unable to access 'https://x-access-token:{TOKEN}@github.com/o/r"
                     f".git/': The requested URL returned error: 403")
    assert TOKEN not in said and "x-access-token" not in said and "***@github.com" in said
    assert TOKEN not in last_line(f"remote: invalid token {TOKEN}")
    assert last_line("fatal: could not open /srv/internal/x6-secret-path/x") == "fatal: could not open <path>"
    assert git_failure("git fetch failed", 1, "")["error"] == "git fetch failed"  # nothing known:


def test_the_platforms_full_disk_pauses_with_the_environment_as_cause():
    from app.services.workflow_runs.pause_causes import _data
    from app.services.workflow_runs.platform.dispatch import read_outcome

    outcome = read_outcome(git_failure("git clone failed", 128, "fatal: No space left on device"))
    assert outcome.failure_class == "environment_not_ready"
    assert _data()["action_failed_classes"]["environment_not_ready"] == "environment"


@pytest.mark.asyncio
async def test_a_transient_failure_is_tried_again_and_a_lasting_one_is_not(monkeypatch):
    monkeypatch.setattr(git_errors, "BACKOFF_SECONDS", (0.0, 0.0))
    answers = [(128, "", "fatal: unable to access '...': Could not resolve host: github.com"), (0, "ok", "")]
    calls = []

    async def once(command, **_):
        calls.append(command)
        return answers.pop(0)

    assert await run_with_retry(once, ["git", "clone", "u", "d"]) == (0, "ok", "")
    assert len(calls) == 2
    calls.clear()

    async def refused(command, **_):
        calls.append(command)
        return 128, "", "fatal: Authentication failed"

    assert (await run_with_retry(refused, ["git", "push", "origin", "b"]))[0] == 128 and len(calls) == 1
    calls.clear()

    async def stalled(command, **_):
        calls.append(command)
        return 124, "", "git timed out after 1800 s"

    assert (await run_with_retry(stalled, ["git", "fetch"]))[0] == 124 and len(calls) == 1  # never 2x 30 min more


@pytest.mark.asyncio
async def test_a_real_clone_failure_reaches_the_step_with_its_class(tmp_path):
    from app.tools.connectors.cloud_common import _run_subprocess
    from app.tools.connectors.github_source_control import _git_failure

    code, _, err = await _run_subprocess(["git", "clone", str(tmp_path / "missing.git"), str(tmp_path / "copy")])
    failure = _git_failure("git clone failed", code, err)
    assert code != 0 and failure["error_class"] == "not_found" and "<path>" in failure["git_said"]
    assert str(tmp_path) not in failure["git_said"]  # the platform's own paths never leave it


def test_the_askpass_script_is_one_file_per_provider_and_holds_no_secret():
    from app.tools.connectors.github_source_control_common import _github_git_auth_env_for_token
    from app.tools.connectors.gitlab_source_control_common import _gitlab_git_auth_env_for_token

    root = Path(tempfile.gettempdir())
    before = {path.name for path in root.glob("octryx-*-askpass-*")}
    first, second = _github_git_auth_env_for_token(TOKEN), _github_git_auth_env_for_token("ghp_" + "B" * 36)
    assert first["GIT_ASKPASS"] == second["GIT_ASKPASS"] and first["OCTRYX_GITHUB_SECRET"] == TOKEN
    script = Path(first["GIT_ASKPASS"])
    assert TOKEN not in script.read_text(encoding="utf-8") and oct(script.parent.stat().st_mode)[-3:] == "700"
    gitlab = _gitlab_git_auth_env_for_token("glpat-" + "C" * 20)["GIT_ASKPASS"]
    assert gitlab != first["GIT_ASKPASS"] and Path(gitlab).parent == script.parent
    assert {path.name for path in root.glob("octryx-*-askpass-*")} == before  # no folder per call
    answered = subprocess.run([str(script), "Password for 'https://github.com':"], capture_output=True, text=True,
                              env={"OCTRYX_GITHUB_SECRET": TOKEN}, check=True)
    assert answered.stdout.strip() == TOKEN  # the script still answers git from the environment
