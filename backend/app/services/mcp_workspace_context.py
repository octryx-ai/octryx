"""The workspace a tool call is governed by, resolved from server-owned context only.

Every MCP gate (capabilities, resources and prompts) and the REST connector surface decide against
this one resolution, so no path can disagree with another about which workspace a call addresses.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..tools.context import ToolContext


@dataclass(frozen=True, slots=True)
class WorkspaceContextResolution:
    """The workspace a ToolContext authoritatively addresses, or why it cannot."""

    workspace_id: str
    reason: str
    matched_rule: str

    @property
    def resolved(self) -> bool:
        return bool(self.workspace_id)


def resolve_workspace_context(context: ToolContext) -> WorkspaceContextResolution:
    """Resolve the active workspace from server-owned context only.

    Two context shapes exist in the tree and both are authoritative:

    - a chat turn puts the active project into
      ``project_config["project_id"]`` (``agent/core/context/run_context_config``);
    - flow/DAG and other worker paths pass the caller's single
      project through ``ToolContext.project_ids`` while their ``project_config``
      is the raw project config (it carries ``mcp_policy`` but no project id).

    ``project_config["project_id"]`` wins when present. Otherwise exactly one
    distinct project id in the context resolves; zero ids and several competing
    ids stay unverifiable and deny. No model-supplied argument is ever consulted,
    so a tool call cannot choose the workspace it is governed by.
    """
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
    """Return the resolved workspace id; an empty string means unverifiable."""
    return resolve_workspace_context(context).workspace_id


__all__ = ["WorkspaceContextResolution", "resolve_workspace_context", "workspace_id_for_context"]
