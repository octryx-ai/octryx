"""Private helper functions shared by workspace and CLI runtime tools."""

from __future__ import annotations

import os
import platform
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...services.repository_bootstrap import ensure_workspace_repository
from ._runtime_cli_command_helpers import command_likely_writes_workspace as _command_likely_writes_workspace_impl
from ._runtime_cli_command_helpers import command_resolution_error as _command_resolution_error_impl
from ._runtime_cli_command_helpers import contains_shell_control_operators as _contains_shell_control_operators_impl
from ._runtime_cli_repo_resolution import infer_repo_cwd_for_command as _infer_repo_cwd_for_command_impl
from ._runtime_cli_repo_resolution import normalize_allowed_repos as _normalize_allowed_repos_impl
from ._runtime_cli_search_filters import apply_search_query_filters as _apply_search_query_filters_impl
from ._runtime_cli_search_filters import normalize_domain_token as _normalize_domain_token_impl
from ._runtime_cli_search_filters import search_result_allowed as _search_result_allowed_impl
from ._runtime_code_intelligence_provenance import _code_intelligence_provenance as _code_intelligence_provenance_impl
from ._runtime_code_intelligence_provenance import (
    _with_code_intelligence_provenance as _with_code_intelligence_provenance_impl,
)
from ._runtime_repo_source_selection import (
    _select_repository_code_candidates as _select_repository_code_candidates_impl,
)
from ._runtime_repo_source_selection import (
    _select_repository_readme_candidates as _select_repository_readme_candidates_impl,
)

MAX_OUTPUT_CHARS = 8000


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n...[truncated]"


def _normalize_domain_token(value: str) -> str:
    return _normalize_domain_token_impl(value)


def _search_result_allowed(
    result: dict[str, Any],
    *,
    include_domains: list[str],
    exclude_domains: list[str],
    exclude_terms: list[str],
    exclude_preprints: bool,
) -> bool:
    return _search_result_allowed_impl(
        result,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        exclude_terms=exclude_terms,
        exclude_preprints=exclude_preprints,
    )


def _apply_search_query_filters(
    query: str,
    *,
    include_domains: list[str],
    exclude_domains: list[str],
    exclude_terms: list[str],
    exclude_preprints: bool,
) -> str:
    return _apply_search_query_filters_impl(
        query,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        exclude_terms=exclude_terms,
        exclude_preprints=exclude_preprints,
    )


def _contains_shell_control_operators(command: str) -> bool:
    return _contains_shell_control_operators_impl(command)


def _command_likely_writes_workspace(argv: list[str]) -> bool:
    return _command_likely_writes_workspace_impl(argv)


def _workspace_root(context: ToolContext) -> Path:
    return Path(context.workspace_root or Path.cwd()).resolve()


def _code_intelligence_provenance(result: dict[str, Any]) -> dict[str, Any]:
    return _code_intelligence_provenance_impl(result)


def _with_code_intelligence_provenance(result: dict[str, Any]) -> dict[str, Any]:
    return _with_code_intelligence_provenance_impl(
        result,
        provenance_builder=_code_intelligence_provenance,
    )


async def _ensure_repository_for_write(context: ToolContext) -> dict[str, Any] | None:
    try:
        result = await ensure_workspace_repository(
            workspace_root=_workspace_root(context),
            project_config=context.project_config,
            session_id=context.session_id,
            reason="write",
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc), "provider": "bootstrap"}
    return result if result.get("status") != "skipped" else None


def _normalize_allowed_repos(config: dict[str, Any]) -> list[dict[str, Any]]:
    return _normalize_allowed_repos_impl(config)




def _infer_repo_cwd_for_command(
    command: str,
    *,
    cwd: Path,
    workspace_root: Path,
    context: ToolContext,
) -> tuple[dict[str, Any] | None, Path]:
    return _infer_repo_cwd_for_command_impl(
        command,
        cwd=cwd,
        workspace_root=workspace_root,
        context=context,
    )




def _resolve_effective_command(
    command: str,
    *,
    cwd: Path,
    context: ToolContext,
    script_resolver: Callable[..., tuple[str, dict[str, Any] | None, Path]],
) -> tuple[str, dict[str, Any] | None, Path]:
    """The command to run (a resolved repository script), its resolution facts and the directory to run it in.

    ``script_resolver`` is the caller's script resolution, looked up in the calling tool's module."""
    workspace_root = _workspace_root(context)
    effective_command, resolution, effective_cwd = script_resolver(
        command,
        cwd=cwd,
        workspace_root=workspace_root,
        context=context,
    )
    repo_resolution, repo_cwd = _infer_repo_cwd_for_command(
        command,
        cwd=effective_cwd,
        workspace_root=workspace_root,
        context=context,
    )
    if repo_resolution:
        resolution = {**(resolution or {}), "repo_resolution": repo_resolution}
        if repo_cwd != effective_cwd:
            effective_cwd = repo_cwd
    return effective_command, resolution, effective_cwd


def _command_resolution_error(
    *,
    command: str,
    cwd: Path,
    resolution: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _command_resolution_error_impl(command=command, cwd=cwd, resolution=resolution)


def _system_command_hints(system_name: str) -> dict[str, str]:
    normalized = system_name.lower()
    if normalized == "darwin":
        return {
            "recent_date": "date -v-5d +%Y-%m-%d",
            "notes": "Use BSD/macOS date flags like -v instead of GNU date -d.",
        }
    if normalized == "windows":
        return {
            "recent_date": '(Get-Date).AddDays(-5).ToString("yyyy-MM-dd")',
            "notes": "Prefer PowerShell syntax instead of Unix date commands.",
        }
    return {
        "recent_date": 'date -d "5 days ago" +%Y-%m-%d',
        "notes": "GNU coreutils syntax is available.",
    }


def detect_system_context(workspace_root: str | None = None) -> dict[str, Any]:
    root = Path(workspace_root or Path.cwd()).resolve()
    shell_path = os.environ.get("SHELL") or os.environ.get("COMSPEC") or ""
    shell_name = Path(shell_path).name if shell_path else None
    system_name = platform.system()
    available_binaries = {
        binary: resolved
        for binary in ["git", "python3", "python", "node", "npm", "npx", "rg", "kubectl", "aws", "docker"]
        if (resolved := shutil.which(binary))
    }
    return {
        "os_name": system_name,
        "os_release": platform.release(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "shell": shell_name,
        "shell_path": shell_path or None,
        "workspace_root": str(root),
        "cwd": str(Path.cwd().resolve()),
        "available_binaries": available_binaries,
        "command_hints": _system_command_hints(system_name),
    }


def _resolve_tool_path(context: ToolContext, raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    candidate = Path(str(raw_path)).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    return str((_workspace_root(context) / candidate).resolve())


def _shorten_text_block(value: str, *, max_chars: int = 1400) -> str:
    text = re.sub(r"\n{3,}", "\n\n", value.strip())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _select_repository_readme_candidates(
    repo_path: Path, status_payload: dict[str, Any], *, workspace_root: Path
) -> list[tuple[str, str]]:
    return _select_repository_readme_candidates_impl(
        repo_path,
        status_payload,
        workspace_root=workspace_root,
    )


def _select_repository_code_candidates(
    repo_path: Path, analysis_payload: dict[str, Any], *, workspace_root: Path
) -> list[tuple[str, str]]:
    return _select_repository_code_candidates_impl(
        repo_path,
        analysis_payload,
        workspace_root=workspace_root,
    )
