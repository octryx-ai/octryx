"""The workspace a tool call is governed by, resolved from server-owned context only. Every MCP gate decides against
this one resolution."""

from __future__ import annotations

from dataclasses import dataclass

from ..tools.context import ToolContext


@dataclass(frozen=True, slots=True)
class WorkspaceContextResolution:
    workspace_id: str
    reason: str
    matched_rule: str

    @property
    def resolved(self) -> bool:
        return bool(self.workspace_id)


def resolve_workspace_context(context: ToolContext) -> WorkspaceContextResolution:
    # Server-owned context only: no model argument chooses the workspace it is governed by; zero or several ids deny.
    project_config = context.project_config if isinstance(context.project_config, dict) else {}
    configured = str(project_config.get("project_id") or "").strip()
    if configured:
        return WorkspaceContextResolution(configured, "", "project_config_project_id")
    raw_project_ids = context.project_ids if isinstance(context.project_ids, (list, tuple, set)) else ()
    candidates = sorted({str(value).strip() for value in raw_project_ids if str(value or "").strip()})
    if len(candidates) == 1:
        return WorkspaceContextResolution(candidates[0], "", "single_context_project")
    if len(candidates) > 1:
        return WorkspaceContextResolution("", "ambiguous_workspace_context", "ambiguous_context")
    return WorkspaceContextResolution("", "missing_workspace_context", "unverifiable_context")


def workspace_id_for_context(context: ToolContext) -> str:
    return resolve_workspace_context(context).workspace_id


__all__ = ["WorkspaceContextResolution", "resolve_workspace_context", "workspace_id_for_context"]
