"""Subprocess output in runtimes, processes and git helpers is either closed facts or redacted."""

from __future__ import annotations

import sys
import uuid

import pytest

from app.models import RuntimeProcess, Session
from app.services.durable_process_runtime import configure_durable_process_runtime
from app.services.execution_runtime import ExecutionRuntimeResult, execute_with_runtime
from app.services.repository_bootstrap import local as bootstrap_local
from app.services.worktree import service as worktree_service
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.conftest import shared_test_session_factory

TOKEN = ("ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123")
CRED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
LEAK_TEXT = f"fatal: auth {TOKEN} for {CRED_URL} at {INTERNAL_PATH}"
SECRETS = (TOKEN, "tok3n")


def _assert_no_leak(value: object, *, allow_path: bool = False) -> None:
    text = repr(value)
    for secret in SECRETS:
        assert secret not in text
    if not allow_path:
        assert INTERNAL_PATH not in text


@pytest.mark.asyncio
async def test_repository_bootstrap_git_failure_keeps_only_closed_facts(monkeypatch, tmp_path):
    async def failing_git(command, *, cwd, timeout_sec=120):
        return 128, LEAK_TEXT, LEAK_TEXT

    monkeypatch.setattr(bootstrap_local, "run_git", failing_git)

    result = await bootstrap_local.initialize_local_repository(
        repo_path=tmp_path / "repo",
        repo_name="repo",
        default_branch="main",
        create_readme=False,
        create_gitignore=False,
        initial_commit=True,
        initial_commit_message="init",
        remote_url=CRED_URL,
        timeout_sec=10,
    )

    assert result == {"error": "git init failed", "error_code": "repository_git_init_failed", "exit_code": 128}
    _assert_no_leak(result)


@pytest.mark.asyncio
async def test_worktree_git_failure_raises_closed_facts(monkeypatch, tmp_path):
    async def failing_runtime(**kwargs):
        return ExecutionRuntimeResult(
            exit_code=128, stdout=LEAK_TEXT, stderr=LEAK_TEXT, timed_out=False, metadata={}
        )

    monkeypatch.setattr(worktree_service, "execute_with_runtime", failing_runtime)

    with pytest.raises(RuntimeError) as excinfo:
        await worktree_service._run_git("worktree", "add", cwd=tmp_path)

    assert str(excinfo.value) == "git_command_failed subcommand=worktree exit_code=128"
    _assert_no_leak(str(excinfo.value))


@pytest.mark.asyncio
async def test_execution_runtime_result_is_redacted_but_keeps_the_output(tmp_path):
    async def leaking_host_command(**kwargs):
        return ExecutionRuntimeResult(
            exit_code=1,
            stdout=f"tests passed: 12\n{LEAK_TEXT}\n",
            stderr=f"warning: {LEAK_TEXT}",
            timed_out=False,
            metadata={"provider": "host", "containerized": False},
        )

    result = await execute_with_runtime(
        db=None,
        project_config={"execution_runtime_provider": "host"},
        command=["pytest"],
        cwd=tmp_path,
        workspace_root=tmp_path,
        timeout_sec=10,
        host_command_fn=leaking_host_command,
    )

    _assert_no_leak((result.stdout, result.stderr), allow_path=True)
    assert "tests passed: 12" in result.stdout
    assert "https://[redacted]@host/x.git" in result.stdout
    assert INTERNAL_PATH in result.stderr
    assert result.exit_code == 1


@pytest.mark.committed_db
@pytest.mark.asyncio
async def test_durable_process_tails_are_redacted_when_stored_and_returned(db, tmp_path, auth_user):
    configure_durable_process_runtime(shared_test_session_factory)
    session = Session(id=f"x6-process-{uuid.uuid4()}", user_id=auth_user.id, metadata_={})
    db.add(session)
    await db.commit()
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={},
        workspace_root=str(tmp_path),
        db=db,
    )
    script = tmp_path / "leak.py"
    script.write_text(
        "import sys\n"
        f"print('build ok ' + {LEAK_TEXT!r})\n"
        f"print('warn ' + {LEAK_TEXT!r}, file=sys.stderr)\n",
        encoding="utf-8",
    )

    started = await execute_tool(
        "start_runtime_process", {"command": f"{sys.executable} {script}", "timeout_sec": 10}, context
    )
    collected = await execute_tool(
        "collect_runtime_process", {"process_id": started["process_id"], "wait_seconds": 5}, context
    )

    assert collected["status"] == "completed"
    assert "build ok" in collected["stdout_tail"]
    assert "warn" in collected["stderr_tail"]
    _assert_no_leak((collected["stdout_tail"], collected["stderr_tail"]), allow_path=True)
    row = await db.get(RuntimeProcess, started["process_id"])
    assert row is not None
    _assert_no_leak((row.stdout_tail, row.stderr_tail), allow_path=True)



@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
