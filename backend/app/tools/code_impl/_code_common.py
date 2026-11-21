"""Shared helpers for code workspace tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.context import ToolContext
from app.tools.runtime_impl._runtime_cwd_resolution import _resolve_cwd

from ...services.repository_bootstrap import ensure_workspace_repository

MAX_MATCHES = 100
MAX_OUTPUT_CHARS = 8000


def _resolve_workspace_path(
    raw: str,
    workspace_root: str | None,
    *,
    context: ToolContext | None = None,
    allow_repo_fallback: bool = False,
    allow_missing: bool = False,
) -> Path:
    return _resolve_cwd(
        workspace_root,
        raw,
        context=context,
        allow_repo_fallback=allow_repo_fallback,
        allow_missing=allow_missing,
    )


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


async def _ensure_repository_for_write(context: ToolContext) -> dict[str, Any] | None:
    workspace = Path(context.workspace_root) if context.workspace_root else Path.cwd()
    try:
        result = await ensure_workspace_repository(
            workspace_root=workspace,
            project_config=context.project_config,
            session_id=context.session_id,
            reason="write",
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc), "provider": "bootstrap"}
    return result if result.get("status") != "skipped" else None
