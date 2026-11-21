"""System and repository bootstrap runtime tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.tools.context import ToolContext

from ...services.repository_bootstrap import (
    ensure_workspace_repository,
    find_git_root,
    get_repository_bootstrap_config,
)
from ._runtime_cli_helpers import _workspace_root, detect_system_context


class GetSystemContextTool:
    """Return the current operating system and workspace context details."""

    name = "get_system_context"
    description = "Return the current operating system, shell, workspace root, and commonly available binaries."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        if context.system_context:
            return context.system_context
        return detect_system_context(context.workspace_root)


class GetCurrentTimeTool:
    """Return local and UTC time values useful for scheduling and reporting."""

    name = "get_current_time"
    description = (
        "Return the current local and UTC time without relying on shell-specific date commands. "
        "When relative_days is provided, use target_local_date for the calendar date in the local timezone."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict:
        now_local = datetime.now().astimezone()
        now_utc = now_local.astimezone(UTC)
        relative_days = int(params.get("relative_days") or 0)
        target_local = now_local + timedelta(days=relative_days)
        target_utc = target_local.astimezone(UTC)
        return {
            "local_time_iso": now_local.isoformat(),
            "utc_time_iso": now_utc.isoformat(),
            "local_date": now_local.date().isoformat(),
            "utc_date": now_utc.date().isoformat(),
            "timezone_name": str(now_local.tzinfo),
            "utc_offset": now_local.strftime("%z"),
            "relative_days": relative_days,
            "target_local_time_iso": target_local.isoformat(),
            "target_utc_time_iso": target_utc.isoformat(),
            "target_local_date": target_local.date().isoformat(),
            "target_utc_date": target_utc.date().isoformat(),
        }


class BootstrapWorkspaceRepositoryTool:
    """Ensure a local workspace is backed by a git repository."""

    name = "bootstrap_workspace_repository"
    description = (
        "Ensure the current workspace is backed by a git repository, optionally creating a GitHub or Bitbucket remote."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict:
        workspace_root = _workspace_root(context)
        existing_root = find_git_root(workspace_root)
        bootstrap = await ensure_workspace_repository(
            workspace_root=workspace_root,
            project_config=context.project_config,
            session_id=context.session_id,
            reason="manual",
            timeout_sec=max(20, min(int(params.get("timeout_sec") or 180), 600)),
        )
        config = get_repository_bootstrap_config(context.project_config)
        return {
            "workspace_root": str(workspace_root),
            "existing_repository": str(existing_root) if existing_root else None,
            "config": config,
            "bootstrap": bootstrap,
        }


__all__ = [
    "GetSystemContextTool",
    "GetCurrentTimeTool",
    "BootstrapWorkspaceRepositoryTool",
]
