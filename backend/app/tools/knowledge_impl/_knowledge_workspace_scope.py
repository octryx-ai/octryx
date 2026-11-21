"""Server-owned Workspace scope for the knowledge dispatch owners.

The knowledge tools resolve their project through ``_resolve_project``, which
*prefers the model-supplied* ``project_id`` parameter (``_knowledge_common.py``
``_current_project_id``). For a read inside the caller's own Workspaces that is
acceptable, but it must never be what decides whose ``model_policy`` governs a
provider dispatch: a model could otherwise name a Workspace with a wider alias
grant and borrow it for the turn it is running in.

So the scope this module builds has two parts, and both come from the server:

- ``anchor_ids`` — the Workspaces whose policy must admit the alias. The
  ToolContext's own project (stamped into ``project_config`` server-side when the
  turn was prepared) always comes first, so it is the Workspace whose verified
  admission is carried to the driver; the project the tool resolved is added, and
  because the admission boundary admits a multi-Workspace scope by *intersection*,
  an alias then needs both grants. Adding a Workspace can only narrow the result.
- ``authorized_ids`` — the actor's own Workspaces (``ToolContext.project_ids``,
  membership- and group-derived, plus the server-stamped anchor). Passed to the
  boundary as ``authorized_project_ids``, so a project outside it is refused as
  ``project_context_not_authorized`` before any policy row is trusted.

``cross_workspace`` is the same check made available to the tool itself, for the
owners that must refuse the whole call rather than only the dispatch.
"""

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
    """One knowledge tool call's server-owned Workspace scope."""

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
        """The bounded payload a tool returns instead of acting cross-Workspace.

        Shaped like ``DispatchAdmission.to_result()`` so an operator reads one
        vocabulary whether the refusal came from the boundary or from the tool.
        """

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
    """Authorize a model-requested project before any project row is read.

    ``project_id`` is the raw tool argument, not a value already resolved from
    the database. The turn's server-stamped project is mandatory: without it a
    model could choose whichever one of the actor's Workspaces has the widest
    model grant. A requested secondary Workspace is accepted only when it is in
    the server-owned authorization set, after which callers may safely load that
    exact id.
    """

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
