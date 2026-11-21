"""Contract: code quality, git intelligence and coding validation never return raw process text.

Failure diagnostics become closed facts (error code + exit status). Output that is a genuine
product result (a test run, validation evidence) is kept, but only through
``redact_process_output``: tokens and URL userinfo are gone, the useful content stays.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.code_quality_service import run_test_suite
from app.services.coding_validation import build_validation_outcome
from app.services.git_intelligence.analysis import git_file_intelligence_impl
from app.services.git_intelligence.diagnostics import git_function_blame_impl

FAKE_TOKEN = ("ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123")
CREDENTIALED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
LEAKY_TEXT = f"fatal: could not read {CREDENTIALED_URL} token={FAKE_TOKEN} at {INTERNAL_PATH}"


def _assert_no_leak(value: Any, *, allow_path: bool = False) -> None:
    text = repr(value)
    assert FAKE_TOKEN not in text
    assert "user:tok3n" not in text
    if not allow_path:
        assert INTERNAL_PATH not in text


class _RuntimeResult:
    def __init__(self, *, exit_code: int, stdout: str, stderr: str, timed_out: bool = False) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.metadata = {"provider": "local"}


@pytest.mark.asyncio
async def test_test_run_output_is_kept_redacted(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_execute_with_runtime(**kwargs):
        return _RuntimeResult(
            exit_code=1,
            stdout=f"FAILED tests/test_demo.py::test_bad - AssertionError\n{LEAKY_TEXT}\n1 failed",
            stderr=LEAKY_TEXT,
        )

    monkeypatch.setattr("app.services.code_quality_service.execute_with_runtime", fake_execute_with_runtime)

    result = await run_test_suite(cwd=repo)

    _assert_no_leak(result["stdout"], allow_path=True)
    _assert_no_leak(result["stderr"], allow_path=True)
    assert "FAILED tests/test_demo.py::test_bad" in result["stdout"]
    assert "https://[redacted]@host/x.git" in result["stdout"]
    assert result["failed_tests"] == ["tests/test_demo.py::test_bad"]
    assert result["all_green"] is False


@pytest.mark.asyncio
async def test_test_run_timeout_is_a_closed_fact(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_execute_with_runtime(**kwargs):
        return _RuntimeResult(exit_code=124, stdout="", stderr=LEAKY_TEXT, timed_out=True)

    monkeypatch.setattr("app.services.code_quality_service.execute_with_runtime", fake_execute_with_runtime)
    from app.services.code_quality_service import _run_exec

    result = await _run_exec(["pytest"], cwd=repo, timeout_sec=5)

    _assert_no_leak(result)
    assert result["error_code"] == "command_timed_out"
    assert result["exit_code"] == 124


@pytest.mark.asyncio
async def test_git_intelligence_failures_are_closed_facts(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")

    async def failing_git(args, **kwargs):
        return {"exit_code": 128, "stdout": LEAKY_TEXT, "stderr": LEAKY_TEXT}

    log_result = await git_file_intelligence_impl(cwd=tmp_path, file_path="app.py", run_git=failing_git)
    blame_result = await git_function_blame_impl(
        cwd=tmp_path, file_path="app.py", symbol="handler", run_git=failing_git
    )

    for result, code in ((log_result, "git_log_failed"), (blame_result, "git_blame_failed")):
        _assert_no_leak(result)
        assert "fatal" not in repr(result)
        assert result["error_code"] == code
        assert result["exit_code"] == 128


@pytest.mark.asyncio
async def test_git_log_data_is_kept_redacted(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    log_line = f"COMMIT\x1fabc123\x1f2026-09-01T10:00:00+00:00\x1fDev\x1fdev@example.com\x1fpush to {CREDENTIALED_URL} {FAKE_TOKEN}"

    async def git(args, **kwargs):
        return {"exit_code": 0, "stdout": f"{log_line}\napp.py\n", "stderr": LEAKY_TEXT}

    result = await git_file_intelligence_impl(cwd=tmp_path, file_path="app.py", run_git=git)

    _assert_no_leak(result)
    assert "dev@example.com" in repr(result)


def test_validation_evidence_is_redacted_and_platform_error_text_is_dropped():
    failed = build_validation_outcome(
        command="pytest -q",
        cwd="/repo",
        exit_code=1,
        stdout=f"1 failed\n{LEAKY_TEXT}",
        stderr=LEAKY_TEXT,
    )
    _assert_no_leak(failed["evidence"], allow_path=True)
    assert "1 failed" in failed["evidence"]["stdout_excerpt"]
    assert failed["status"] == "failed"

    not_runnable = build_validation_outcome(command="pytest -q", cwd="/repo", error=LEAKY_TEXT)
    _assert_no_leak(not_runnable)
    assert not_runnable["evidence"] == {"stdout_excerpt": "", "stderr_excerpt": ""}


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
