"""Runtime policy helpers for workspace mutation tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...services.coding_policy_runtime import enforce_workspace_path_policy
from ..context import ToolContext


async def evaluate_workspace_mutation_policy(
    context: ToolContext,
    *,
    tool_name: str,
    target_paths: list[Path | str],
    proposed: dict[Path | str, str] | None = None,
) -> dict[str, Any]:
    relative_paths = [_relative_workspace_path(context, path) for path in target_paths]
    # No file tool writes git's internals: a planted hook, ``.git/config`` (fsmonitor, aliases,
    # filters) or ``info/attributes`` would make a later git run a program. Before any configurable policy.
    if internal := [path for path in relative_paths if ".git" in path.casefold().split("/")]:
        return {"status": "blocked", "blocking": True, "tool_name": tool_name, "paths": relative_paths,
                "reason": f"Git's internal files are never written by a tool ({internal[0]}).",
                "outcomes": [{"effect": "block", "rule": "git_internals_write", "path": internal[0]}],
                "summary": {"pass": 0, "warn": 0, "review_required": 0, "block": 1, "skipped": 0}}
    return await enforce_workspace_path_policy(
        context.db,
        user_id=context.user_id,
        session_id=context.session_id,
        project_id=_context_project_id(context),
        work_item_id=_context_work_item_id(context),
        tool_name=tool_name,
        paths=relative_paths,
        proposed={_relative_workspace_path(context, path): text for path, text in (proposed or {}).items()},
    )


def _relative_workspace_path(context: ToolContext, path: Path | str) -> str:
    raw_path = Path(path)
    try:
        workspace_root = Path(str(context.workspace_root or ".")).expanduser().resolve()
        absolute_path = raw_path.expanduser().resolve() if raw_path.is_absolute() else (workspace_root / raw_path).resolve()
        return str(absolute_path.relative_to(workspace_root)).replace("\\", "/")
    except (OSError, ValueError):
        return str(raw_path).replace("\\", "/").lstrip("/")


def _context_project_id(context: ToolContext) -> str | None:
    config = context.project_config or {}
    configured = str(config.get("project_id") or "").strip()
    if configured:
        return configured
    return str(context.project_ids[0]).strip() if context.project_ids else None


def _context_work_item_id(context: ToolContext) -> str | None:
    config = context.project_config or {}
    candidates = [
        config.get("work_item_id"),
        config.get("secure_work_work_item_id"),
    ]
    secure_work_execution = config.get("secure_work_execution")
    if isinstance(secure_work_execution, dict):
        candidates.append(secure_work_execution.get("work_item_id"))
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return None


__all__ = ["evaluate_workspace_mutation_policy"]
