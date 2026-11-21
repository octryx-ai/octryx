"""What a server command can reach besides its classification.

- layer 3: git in a server command runs nothing a working copy configures — a hook planted directly as a file does
  not run on ``git commit``, a planted ``core.fsmonitor`` does not run on ``git status`` (``execute_with_runtime``,
  the platform's ``safe_git``), whatever the classifier said;
- the environment: a server shell sees none of the API's secrets (database URL, JWT secret, IRSA role), also when the
  caller spreads ``os.environ`` into ``env``;
- the file tools: a write into ``.git/`` is refused, a read outside the workspace (``/proc/1/environ``) too;
- the audit: a refused and an executed command each leave exactly one ``audit_log`` row with the masked command and
  never its output; without a place to write the row the command does not run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.execution_runtime import ExecutionRuntimeConfig, execute_with_runtime
from app.services.execution_runtime.command_audit import (
    AUDIT_UNAVAILABLE,
    CommandActor,
    command_actor,
    masked_command,
)
from app.tools.context import ToolContext
from tests.phased_workflow_fixtures import admin_user

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


async def _host(db, project_config=None):
    return ExecutionRuntimeConfig(provider="host")


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.txt").write_text("a\n")
    return repo


def _script(path: Path, marker: Path) -> Path:
    path.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
    path.chmod(0o755)
    return path


async def _run(command: str, repo: Path):
    return await execute_with_runtime(db=None, project_config={}, command=command, cwd=repo, workspace_root=repo,
                                      timeout_sec=30, shell=True, resolve_config_fn=_host)


@pytest.mark.asyncio
async def test_a_planted_pre_commit_hook_never_runs_on_a_server_commit(tmp_path):
    repo, marker = _repo(tmp_path), tmp_path / "hook-ran"
    _script(repo / ".git" / "hooks" / "pre-commit", marker)  # written directly, as a file tool would
    result = await _run("git add a.txt && git -c user.name=bot -c user.email=bot@x.invalid commit -q -m m", repo)
    assert result.exit_code == 0, result.stderr
    assert not marker.exists()
    # The same commit without the server's environment runs the hook: the test plants a real one.
    (repo / "a.txt").write_text("b\n")
    subprocess.run("git add a.txt && git -c user.name=bot -c user.email=bot@x.invalid commit -q -m n", shell=True,
                   cwd=repo, check=True)
    assert marker.exists()


@pytest.mark.asyncio
async def test_a_planted_fsmonitor_never_runs_on_a_server_status(tmp_path):
    from app.services.workflow_runs import safe_git

    repo, marker = _repo(tmp_path), tmp_path / "fsmonitor-ran"
    monitor = _script(tmp_path / "fsmonitor.sh", marker)
    with (repo / ".git" / "config").open("a") as config:
        config.write(f"[core]\n\tfsmonitor = {monitor}\n")
    result = await _run("git status --porcelain", repo)
    assert result.exit_code == 0, result.stderr
    assert (await safe_git.git(repo, "status", "--porcelain"))[0] == 0
    assert not marker.exists()
    subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=False, capture_output=True)
    assert marker.exists()  # plain git would have run it


@pytest.mark.asyncio
async def test_a_server_shell_sees_none_of_the_api_secrets(tmp_path, monkeypatch):
    for name, value in (("DATABASE_URL", "postgresql://u:dbsecret@db/x"), ("JWT_SECRET", "jwtsecret-value"),
                        ("AWS_ROLE_ARN", "arn:aws:iam::1:role/api"),
                        ("AWS_WEB_IDENTITY_TOKEN_FILE", "/var/run/secrets/eks/token"),
                        ("KUBERNETES_SERVICE_HOST", "10.0.0.1")):
        monkeypatch.setenv(name, value)
    command = 'echo "db=$DATABASE_URL jwt=$JWT_SECRET role=$AWS_ROLE_ARN wit=$AWS_WEB_IDENTITY_TOKEN_FILE ' \
              'k8s=$KUBERNETES_SERVICE_HOST home=$HOME set=$CALLER_SET"'
    result = await execute_with_runtime(
        db=None, project_config={}, command=command, cwd=tmp_path, workspace_root=tmp_path, timeout_sec=30,
        shell=True, env={**os.environ, "CALLER_SET": "yes"}, resolve_config_fn=_host)
    out = result.stdout
    assert "db= jwt= role= wit= k8s= " in out and "dbsecret" not in out and "jwtsecret" not in out
    assert f"home={os.environ['HOME']}" in out and "set=yes" in out  # the allowlist and the caller's own value


@pytest.mark.asyncio
async def test_file_tools_never_write_git_internals_nor_read_outside_the_workspace(tmp_path):
    from app.tools.runtime_impl._runtime_policy import evaluate_workspace_mutation_policy
    from app.tools.runtime_impl._runtime_workspace_files import ReadWorkspaceFileTool

    repo = _repo(tmp_path)
    context = ToolContext(user_id="u", project_ids=[], roles=["admin"], session_id="s", project_config={},
                          workspace_root=str(repo))
    for target in (".git/hooks/pre-commit", ".git/config", "sub/.GIT/info/attributes"):
        decision = await evaluate_workspace_mutation_policy(context, tool_name="write_workspace_file",
                                                            target_paths=[repo / target])
        assert decision["blocking"] is True and "Git's internal files" in decision["reason"], target
    for path in ("/proc/1/environ", "/proc/self/environ", "/var/run/secrets/kubernetes.io/serviceaccount/token",
                 "../../../../proc/self/environ"):
        result = await ReadWorkspaceFileTool().execute({"path": path}, context)
        assert "error" in result and "content" not in result, path


# --- audit ------------------------------------------------------------------------------------------------------------

async def _rows(db) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).where(AuditLog.resource_type == "server_command")
                                  .order_by(AuditLog.created_at))).scalars())


@pytest.mark.asyncio
async def test_an_executed_command_leaves_one_row_with_its_exit_code_and_no_output(db, tmp_path):
    admin = await admin_user(db)
    token = "ghp_" + "A1b2C3d4" * 5
    with command_actor(CommandActor(db=db, user_id=admin.id, tool_name="bash")):
        result = await execute_with_runtime(
            db=db, project_config={}, command=f"echo output-text-{token[:6]} && echo TOKEN={token} >/dev/null",
            cwd=tmp_path, workspace_root=tmp_path, timeout_sec=30, shell=True, resolve_config_fn=_host)
    assert result.exit_code == 0 and "output-text" in result.stdout
    [row] = await _rows(db)
    assert (row.action, row.user_id, row.details["verdict"], row.details["exit_code"]) == (
        "server_command.executed", admin.id, "executed", 0)
    assert token not in row.details["command"] and "TOKEN=***" in row.details["command"]
    assert "output-text-ghp_A1\n" not in str(row.details) and "stdout" not in row.details


@pytest.mark.asyncio
async def test_a_refused_command_leaves_one_refused_row(db, tmp_path):
    from app.tools.runtime_impl._runtime_bash_web import BashTool

    admin = await admin_user(db)
    context = ToolContext(user_id=admin.id, project_ids=[], roles=["admin"], session_id=None, project_config={},
                          workspace_root=str(tmp_path), db=db)
    with command_actor(CommandActor(db=db, user_id=admin.id, tool_name="bash")):
        result = await BashTool().execute({"command": "kubectl get secrets -A"}, context)
    assert result["error_code"] == "server_build_not_allowed"
    [row] = await _rows(db)
    assert (row.action, row.details["verdict"], row.details["reason"], row.details["command"]) == (
        "server_command.refused", "refused", "server_build_not_allowed", "kubectl get secrets -A")
    assert row.details["exit_code"] is None


@pytest.mark.asyncio
async def test_without_a_place_for_the_row_the_command_does_not_run(tmp_path):
    ran: list = []

    async def host(**kwargs):  # must never run
        ran.append(kwargs)

    with command_actor(CommandActor(db=None, user_id="u", tool_name="bash")):
        result = await execute_with_runtime(db=None, project_config={}, command="git status", cwd=tmp_path,
                                            workspace_root=tmp_path, timeout_sec=5, resolve_config_fn=_host,
                                            host_command_fn=host)
    assert ran == [] and result.exit_code is None and result.metadata["refused"] == AUDIT_UNAVAILABLE


def test_the_stored_command_is_masked_and_bounded():
    masked = masked_command("curl -H 'Authorization: Bearer abc.def' -d password=hunter2 https://x/"
                            + "?k=" + "Z" * 30 + " " + "y " * 1500)
    assert "abc.def" not in masked and "hunter2" not in masked and "Z" * 30 not in masked
    assert "PASSWORD" not in masked and "password=***" in masked and len(masked) == 2000
