from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.code_quality.config import load_repo_code_quality_config
from app.services.code_quality.helpers import command_available, truncate
from app.services.code_quality.lint_sast import lint_and_format_workspace_impl, run_sast_suite_impl
from app.services.code_quality.openrewrite import run_openrewrite_recipe_impl
from app.services.code_quality.patterns import analyze_codebase_patterns_impl
from app.services.code_quality.run_status import (
    COMMAND_NOT_STARTED_CODE,
    COMMAND_TIMED_OUT_CODE,
    NOT_STARTED_EXIT_CODE,
    RUN_FAILED,
    RUN_NOT_STARTED,
    RUN_REFUSED,
    RUN_SUCCEEDED,
    RUN_TIMED_OUT,
    TIMED_OUT_EXIT_CODE,
    bounded_command_timeout,
)
from app.services.code_quality.tests import run_test_suite_impl

from .execution_runtime import execute_with_runtime
from .execution_runtime.foreign_build_guard import guard_server_command


def _truncate(text: str, *, max_chars: int = 8000) -> str:
    return truncate(text, max_chars=max_chars)


async def _run_exec(
    command: list[str],
    *,
    cwd: Path,
    timeout_sec: int = 120,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not command:
        return {"error": "empty command", "status": RUN_NOT_STARTED, "exit_code": 1, "stdout": "", "stderr": ""}
    timeout_sec = bounded_command_timeout(timeout_sec)
    refused = await _refused_server_build(command, cwd=cwd)
    if refused is not None:
        return refused
    runtime_result = await execute_with_runtime(
        db=db,
        project_config=project_config,
        command=command,
        cwd=cwd,
        workspace_root=cwd,
        timeout_sec=timeout_sec,
    )
    return _runtime_result_payload(command, runtime_result, timeout_sec=timeout_sec)


async def _refused_server_build(command: list[str], *, cwd: Path) -> dict[str, Any] | None:
    # Tests, builds and code-loading linters never run on the server (``foreign_build_guard``);
    # a static formatter/scanner (ruff, black, gofmt, bandit, semgrep) does.
    if (server_build := guard_server_command(command, where="code_quality", audit={"cwd": str(cwd)})) is None:
        return None
    from .execution_runtime import command_audit

    try:  # the refused command's one audit row; an executed one is audited by ``execute_with_runtime``
        await command_audit.record(command, verdict="refused", where="code_quality",
                                   reason=str(server_build.get("error_code") or ""))
    except command_audit.CommandAuditUnavailableError:
        pass  # refused either way
    return {**server_build, "status": RUN_REFUSED, "exit_code": None, "stdout": "", "stderr": "",
            "command": command}


def _runtime_result_payload(
    command: list[str], runtime_result: Any, *, timeout_sec: int
) -> dict[str, Any]:
    if runtime_result.timed_out:
        # The runtime's timeout text is never kept; the timeout is a closed fact.
        return {
            "error": f"{COMMAND_TIMED_OUT_CODE} timeout_sec={timeout_sec}",
            "error_code": COMMAND_TIMED_OUT_CODE,
            "status": RUN_TIMED_OUT,
            "timeout_sec": timeout_sec,
            "exit_code": TIMED_OUT_EXIT_CODE,
            "stdout": "",
            "stderr": "",
            "command": command,
            "execution_runtime": runtime_result.metadata,
        }
    if runtime_result.exit_code is None:
        return {
            "error": COMMAND_NOT_STARTED_CODE,
            "error_code": COMMAND_NOT_STARTED_CODE,
            "status": RUN_NOT_STARTED,
            "exit_code": NOT_STARTED_EXIT_CODE,
            "stdout": "",
            "stderr": "",
            "command": command,
            "execution_runtime": runtime_result.metadata,
        }
    return {
        "command": command,
        "status": RUN_SUCCEEDED if runtime_result.exit_code == 0 else RUN_FAILED,
        "exit_code": runtime_result.exit_code,
        "stdout": runtime_result.stdout,
        "stderr": runtime_result.stderr,
        "execution_runtime": runtime_result.metadata,
    }


def _which(command: str) -> str | None:
    return shutil.which(command)


def _command_available(command: list[str], cwd: Path) -> bool:
    return command_available(command, cwd, which_fn=_which)


async def run_test_suite(
    *,
    cwd: Path,
    framework: str | None = None,
    path: str | None = None,
    coverage: bool = False,
    timeout_sec: int = 120,
    previous_failed_tests: list[str] | None = None,
    project_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    return await run_test_suite_impl(
        cwd=cwd,
        framework=framework,
        path=path,
        coverage=coverage,
        timeout_sec=timeout_sec,
        previous_failed_tests=previous_failed_tests,
        project_config=project_config,
        db=db,
        load_config_fn=load_repo_code_quality_config,
        run_exec_fn=_run_exec,
        which_fn=_which,
    )


async def lint_and_format_workspace(
    *,
    cwd: Path,
    auto_fix: bool = False,
    include_sast: bool = True,
    timeout_sec: int = 120,
    project_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    return await lint_and_format_workspace_impl(
        cwd=cwd,
        auto_fix=auto_fix,
        include_sast=include_sast,
        timeout_sec=timeout_sec,
        project_config=project_config,
        db=db,
        load_config_fn=load_repo_code_quality_config,
        run_exec_fn=_run_exec,
        which_fn=_which,
    )


async def run_sast_suite(
    *,
    cwd: Path,
    timeout_sec: int = 120,
    runners: list[str] | None = None,
    project_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    return await run_sast_suite_impl(
        cwd=cwd,
        timeout_sec=timeout_sec,
        runners=runners,
        project_config=project_config,
        db=db,
        load_config_fn=load_repo_code_quality_config,
        run_exec_fn=_run_exec,
        which_fn=_which,
    )


async def run_openrewrite_recipe(
    *,
    cwd: Path,
    recipes: list[str] | None = None,
    recipe_artifacts: list[str] | None = None,
    dry_run: bool = False,
    timeout_sec: int = 300,
    export_datatables: bool = True,
    project_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    return await run_openrewrite_recipe_impl(
        cwd=cwd,
        recipes=recipes,
        recipe_artifacts=recipe_artifacts,
        dry_run=dry_run,
        timeout_sec=timeout_sec,
        export_datatables=export_datatables,
        project_config=project_config,
        db=db,
        load_config_fn=load_repo_code_quality_config,
        run_exec_fn=_run_exec,
        which_fn=_which,
    )


def analyze_codebase_patterns(*, cwd: Path, max_files: int = 20) -> dict[str, Any]:
    return analyze_codebase_patterns_impl(
        cwd=cwd,
        max_files=max_files,
        load_config_fn=load_repo_code_quality_config,
    )


__all__ = [
    "run_test_suite",
    "lint_and_format_workspace",
    "run_sast_suite",
    "run_openrewrite_recipe",
    "analyze_codebase_patterns",
    "_truncate",
    "_run_exec",
    "_which",
    "_command_available",
]
