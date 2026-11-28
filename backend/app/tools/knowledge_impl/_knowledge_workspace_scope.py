"""Server-owned Workspace scope for the knowledge dispatch owners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...services.model_gateway.dispatch_admission import (
    DISPATCH_STATE_ALLOWED,
    DISPATCH_STATE_DENIED,
    DISPATCH_STATE_NEEDS_CONFIGURATION,
    REASON_CONTEXT_MISSING,
    REASON_CONTEXT_NOT_AUTHORIZED,
)
from ..context import ToolContext

# The tool-result error key for a project the actor may not act for. Fixed
# vocabulary: it names the decision, never the project or the policy.
CROSS_WORKSPACE_ERROR = "project_not_authorized"
MISSING_WORKSPACE_ERROR = "project_context_missing"


def _normalized(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    normalized: list[str] = []
    for value in values:
        candidate = str(value or "").strip()
        if candidate and candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class KnowledgeWorkspaceScope:
    anchor_ids: tuple[str, ...]
    authorized_ids: tuple[str, ...]
    selected_project_id: str
    state: str
    reason: str
    cross_workspace: bool

    @property
    def allowed(self) -> bool:
        return self.state == DISPATCH_STATE_ALLOWED

    def denial_result(self, *, owner: str) -> dict[str, Any]:
        return {
            "error": (
                CROSS_WORKSPACE_ERROR
                if self.reason == REASON_CONTEXT_NOT_AUTHORIZED
                else MISSING_WORKSPACE_ERROR
            ),
            "status": self.state,
            "dispatch_owner": owner,
            "admission_reason": self.reason,
            "dispatched": False,
        }


def knowledge_workspace_scope(context: ToolContext, *, project_id: Any) -> KnowledgeWorkspaceScope:
    requested = str(project_id or "").strip()
    server_anchor = str((context.project_config or {}).get("project_id") or "").strip()
    # The server-stamped anchor is authorized by construction: the turn was
    # prepared for it. Everything else has to be one of the actor's own projects.
    authorized_ids = _normalized([*(context.project_ids or []), server_anchor])
    if not server_anchor:
        return KnowledgeWorkspaceScope(
            anchor_ids=(),
            authorized_ids=authorized_ids,
            selected_project_id="",
            state=DISPATCH_STATE_NEEDS_CONFIGURATION,
            reason=REASON_CONTEXT_MISSING,
            cross_workspace=False,
        )
    selected_project_id = requested or server_anchor
    cross_workspace = selected_project_id not in authorized_ids
    return KnowledgeWorkspaceScope(
        anchor_ids=_normalized([server_anchor, selected_project_id]),
        authorized_ids=authorized_ids,
        selected_project_id=selected_project_id,
        state=DISPATCH_STATE_DENIED if cross_workspace else DISPATCH_STATE_ALLOWED,
        reason=REASON_CONTEXT_NOT_AUTHORIZED if cross_workspace else "",
        cross_workspace=cross_workspace,
    )


__all__ = [
    "CROSS_WORKSPACE_ERROR",
    "MISSING_WORKSPACE_ERROR",
    "KnowledgeWorkspaceScope",
    "knowledge_workspace_scope",
]
