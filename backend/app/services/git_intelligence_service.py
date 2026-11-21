from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.git_intelligence.analysis import git_coupling_map_impl, git_file_intelligence_impl
from app.services.git_intelligence.change_summary import git_change_summary_impl
from app.services.git_intelligence.context import (
    git_conflict_predictor_impl,
    git_knowledge_extract_impl,
    git_pr_context_impl,
)
from app.services.git_intelligence.diagnostics import (
    git_function_blame_impl,
    git_hotspot_analysis_impl,
)

from .execution_runtime import execute_with_runtime


async def _run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout_sec: int = 30,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_result = await execute_with_runtime(
        db=db,
        project_config=project_config,
        command=["git", *args],
        cwd=cwd,
        workspace_root=cwd,
        timeout_sec=timeout_sec,
        guard_foreign_build=False,  # the platform's own git (fixed subcommand), not an agent command
    )
    if runtime_result.timed_out:
        # The runtime's timeout text is never kept; the timeout is a closed fact.
        return {
            "error": f"git_command_timed_out timeout_sec={int(timeout_sec)}",
            "error_code": "git_command_timed_out",
            "exit_code": 124,
            "stdout": "",
            "stderr": "",
            "execution_runtime": runtime_result.metadata,
        }
    return {
        "exit_code": runtime_result.exit_code if runtime_result.exit_code is not None else 125,
        "stdout": runtime_result.stdout,
        "stderr": runtime_result.stderr,
        "execution_runtime": runtime_result.metadata,
    }


async def git_file_intelligence(
    *,
    cwd: Path,
    file_path: str,
    days: int = 90,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await git_file_intelligence_impl(
        cwd=cwd,
        file_path=file_path,
        days=days,
        run_git=_run_git,
        db=db,
        project_config=project_config,
    )


async def git_coupling_map(
    *,
    cwd: Path,
    changed_files: list[str],
    threshold: float = 0.6,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await git_coupling_map_impl(
        cwd=cwd,
        changed_files=changed_files,
        threshold=threshold,
        run_git=_run_git,
        db=db,
        project_config=project_config,
    )


async def git_change_summary(
    *,
    cwd: Path,
    paths: list[str],
    days: int = 30,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await git_change_summary_impl(
        cwd=cwd,
        paths=paths,
        days=days,
        run_git=_run_git,
        db=db,
        project_config=project_config,
    )


async def git_hotspot_analysis(
    *,
    cwd: Path,
    days: int = 90,
    top_n: int = 15,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await git_hotspot_analysis_impl(
        cwd=cwd,
        days=days,
        top_n=top_n,
        run_git=_run_git,
        db=db,
        project_config=project_config,
    )


async def git_function_blame(
    *,
    cwd: Path,
    file_path: str,
    symbol: str,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await git_function_blame_impl(
        cwd=cwd,
        file_path=file_path,
        symbol=symbol,
        run_git=_run_git,
        db=db,
        project_config=project_config,
    )


async def git_conflict_predictor(
    *,
    cwd: Path,
    planned_files: list[str],
    open_pull_requests: list[dict[str, Any]] | None = None,
    threshold: float = 0.6,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await git_conflict_predictor_impl(
        cwd=cwd,
        planned_files=planned_files,
        open_pull_requests=open_pull_requests,
        threshold=threshold,
        run_git=_run_git,
        db=db,
        project_config=project_config,
    )


async def git_pr_context(
    *,
    cwd: Path,
    changed_files: list[str],
    pr: dict[str, Any] | None = None,
    days: int = 90,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await git_pr_context_impl(
        cwd=cwd,
        changed_files=changed_files,
        pr=pr,
        days=days,
        run_git=_run_git,
        db=db,
        project_config=project_config,
    )


async def git_knowledge_extract(
    *,
    cwd: Path,
    scope: str = ".",
    extract_types: list[str] | None = None,
    days: int = 90,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await git_knowledge_extract_impl(
        cwd=cwd,
        scope=scope,
        extract_types=extract_types,
        days=days,
        run_git=_run_git,
        db=db,
        project_config=project_config,
    )
