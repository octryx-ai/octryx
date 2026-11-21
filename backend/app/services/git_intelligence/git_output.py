"""Running git for the intelligence tools: the runner type, failures as closed facts, redacted output."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.process_output_redaction import redact_process_output

RunGitFn = Callable[..., Awaitable[dict[str, Any]]]


def git_command_failure(code: str, result: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """A failed git command as closed facts; its stderr (remote URLs, paths) is never kept."""
    exit_code = result.get("exit_code")
    return {
        "error": code,
        "error_code": code,
        "exit_code": exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
        "repo_root": str(repo_root),
    }


def redacted_git_output(result: dict[str, Any]) -> str:
    """Git data the product parses and returns (subjects, authors, file names): redacted first."""
    return redact_process_output(result.get("stdout") or "")


async def _changed_files_for_commit(
    *,
    cwd: Path,
    sha: str,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> list[str]:
    result = await run_git(
        ["show", "--pretty=format:", "--name-only", sha], cwd=cwd, db=db, project_config=project_config
    )
    if result["exit_code"] != 0:
        return []
    return [line.strip() for line in redacted_git_output(result).splitlines() if line.strip()]
