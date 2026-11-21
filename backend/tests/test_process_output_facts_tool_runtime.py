"""Subprocess output in tool runtime results: fixed facts on failures, redacted when kept.

Failure paths (git, office scripts, runtime unavailable) keep only a closed code and
the exit status. Output that is the product result (the bash tool, contract validation
commands, a git diff) is kept, but token-shaped strings and URL userinfo never survive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.execution_runtime import ExecutionRuntimeResult
from app.tools.context import ToolContext
from app.tools.office_impl._office_generated_base import _GeneratedOfficeScriptToolBase
from app.tools.runtime_impl import _runtime_quality_tools_vcs as vcs
from app.tools.runtime_impl._runtime_bash_web import BashTool
from app.tools.runtime_impl._runtime_validation_commands import _run_command

TOKEN = ("ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123")
CRED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
SECRET_TEXT = f"fatal: auth {TOKEN} for {CRED_URL} at {INTERNAL_PATH}"


def _context(workspace: Path) -> ToolContext:
    return ToolContext(
        user_id="test",
        project_ids=[],
        roles=["admin"],
        session_id="test",
        project_config={},
        workspace_root=str(workspace),
    )


def _assert_no_facts_leak(value: object) -> None:
    text = repr(value)
    for secret in (TOKEN, CRED_URL, "tok3n", INTERNAL_PATH):
        assert secret not in text


def _assert_redacted_but_useful(text: str, useful: str) -> None:
    assert TOKEN not in text
    assert "tok3n" not in text
    assert useful in text
    assert INTERNAL_PATH in text


def _runtime(exit_code: int | None, stdout: str = "", stderr: str = "") -> ExecutionRuntimeResult:
    return ExecutionRuntimeResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
        metadata={"provider": "host"},
    )


@pytest.mark.asyncio
async def test_bash_tool_keeps_output_through_the_redactor(monkeypatch, tmp_path):
    async def fake_runtime(**_kwargs):
        return _runtime(1, stdout=f"build ok\n{SECRET_TEXT}\n", stderr=f"warning: {SECRET_TEXT}\n")

    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", fake_runtime)
    result = await BashTool().execute({"command": "echo hi"}, _context(tmp_path))

    assert result["returncode"] == 1
    for key in ("stdout", "stderr", "output"):
        _assert_redacted_but_useful(result[key], "fatal: auth")
    assert "build ok" in result["stdout"]


@pytest.mark.asyncio
async def test_bash_tool_unavailable_runtime_keeps_fixed_facts(monkeypatch, tmp_path):
    async def fake_runtime(**_kwargs):
        return _runtime(None, stderr=SECRET_TEXT)

    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", fake_runtime)
    result = await BashTool().execute({"command": "echo hi"}, _context(tmp_path))

    assert result["error"] == "bash_command_not_started"
    _assert_no_facts_leak(result)


@pytest.mark.asyncio
async def test_cli_command_unavailable_runtime_leaks_nothing_into_validation_evidence(monkeypatch, tmp_path):
    async def fake_runtime(**_kwargs):
        return _runtime(None, stderr=SECRET_TEXT)

    monkeypatch.setattr("app.tools.runtime_impl._runtime_workspace_cli.execute_with_runtime", fake_runtime)
    from app.tools.runtime_impl._runtime_workspace_cli import RunCLICommandTool

    result = await RunCLICommandTool().execute({"command": "terraform validate"}, _context(tmp_path))

    assert result["error"] == "cli_command_not_started"
    assert result["validation_outcome"]["status"] == "not_runnable"
    _assert_no_facts_leak(result)


class _FakeProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self._output = (stdout.encode(), stderr.encode())

    async def communicate(self):
        return self._output

    def kill(self) -> None:  # pragma: no cover - never times out here
        pass


def _fake_git(monkeypatch, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
    async def fake_exec(*_args, **_kwargs):
        return _FakeProcess(returncode, stdout, stderr)

    monkeypatch.setattr(vcs.asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "code"),
    [(vcs.ListWorkspaceGitCommitsTool, "git_log_failed"), (vcs.GetGitDiffTool, "git_diff_failed")],
)
async def test_git_failures_keep_only_the_code_and_exit_status(monkeypatch, tmp_path, tool, code):
    _fake_git(monkeypatch, returncode=128, stdout=SECRET_TEXT, stderr=SECRET_TEXT)

    result = await tool().execute({}, _context(tmp_path))

    assert result["error_code"] == code
    assert result["exit_code"] == 128
    _assert_no_facts_leak(result)


@pytest.mark.asyncio
async def test_git_log_success_drops_stderr_and_git_diff_keeps_a_redacted_diff(monkeypatch, tmp_path):
    _fake_git(monkeypatch, returncode=0, stdout="", stderr=f"warning: {SECRET_TEXT}")
    log_result = await vcs.ListWorkspaceGitCommitsTool().execute({}, _context(tmp_path))
    assert log_result["commit_count"] == 0
    _assert_no_facts_leak(log_result)

    _fake_git(monkeypatch, returncode=0, stdout=f"+remote = {CRED_URL}\n+token = {TOKEN}\n+path {INTERNAL_PATH}\n")
    diff_result = await vcs.GetGitDiffTool().execute({}, _context(tmp_path))
    _assert_redacted_but_useful(diff_result["diff"], "+remote = https://")


@pytest.mark.asyncio
async def test_validation_command_output_is_redacted_and_os_errors_are_fixed(monkeypatch, tmp_path):
    kept = await _run_command(f"printf '%s' 'tests passed {SECRET_TEXT}'", cwd=tmp_path)
    assert kept["ok"] is True
    _assert_redacted_but_useful(kept["output_tail"], "tests passed")

    async def failing_shell(*_args, **_kwargs):
        raise OSError(SECRET_TEXT)

    monkeypatch.setattr("asyncio.create_subprocess_shell", failing_shell)
    failed = await _run_command("make test", cwd=tmp_path)
    assert failed["error_code"] == "validation_command_not_started"
    assert failed["error_type"] == "OSError"
    _assert_no_facts_leak(failed)


@pytest.mark.asyncio
async def test_office_build_script_failure_keeps_fixed_facts(tmp_path):
    script = tmp_path / "deck.pptx.build.py"
    script.write_text(
        f"import sys\nprint({SECRET_TEXT!r})\nprint({SECRET_TEXT!r}, file=sys.stderr)\nsys.exit(2)\n",
        encoding="utf-8",
    )

    error, stdout_text, stderr_text = await _GeneratedOfficeScriptToolBase()._execute_script(script)

    assert error is not None
    assert error["error"] == "office_script_failed exit_code=2"
    assert (stdout_text, stderr_text) == ("", "")
    _assert_no_facts_leak(error)


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
