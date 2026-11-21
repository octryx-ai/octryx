"""Workflow catalog tools: the model proposes a published workflow, the user starts it.

``list_available_workflows`` lists the Workspace's published phased workflows; ``start_workflow``
and ``select_workflow`` (the system-prompt catalog's meta tool) answer with the explicit state of a
key. A workflow never runs inside a chat turn: it starts as a workflow run for a Work item after
the user's confirmation.

Governance note: the tools are ``built_in`` with ``risk="read"`` and no approval requirement:
they change nothing.
"""

from __future__ import annotations

from typing import Any

from ..services.run_admission.denials import WORKFLOW_ARCHIVED
from ..services.run_admission.phased_catalog import WORKFLOW_RUN_REQUIRED
from .context import ToolContext


def _request_analysis_from_context(context: ToolContext) -> dict[str, Any]:
    snapshot = context.turn_context_snapshot if isinstance(context.turn_context_snapshot, dict) else {}
    request_analysis = snapshot.get("request_analysis")
    return request_analysis if isinstance(request_analysis, dict) else {}


_KEYLESS_SELECT_WORKFLOW_COUNTER_KEY = "keyless_select_workflow_calls"


def _count_keyless_select_workflow_calls(context: ToolContext) -> int:
    """Key-less select_workflow attempts already made in this turn.

    The counter lives in the shared turn context snapshot (same place the
    other per-turn audit markers use), so the answer can escalate instead of
    repeating an identical error the model just retries.
    """
    snapshot = context.turn_context_snapshot
    if not isinstance(snapshot, dict):
        return 0
    seen = int(snapshot.get(_KEYLESS_SELECT_WORKFLOW_COUNTER_KEY) or 0)
    snapshot[_KEYLESS_SELECT_WORKFLOW_COUNTER_KEY] = seen + 1
    return seen


def _user_selected_no_workflow(context: ToolContext) -> bool:
    """The user chose "No workflow" for this turn (``workflow_key: none``); the model may not override it."""
    from ..services.workflow_routing.proposal_states import WORKFLOW_PROPOSAL_KEY
    from ..services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

    resolution = _request_analysis_from_context(context).get(ROUTING_RESOLUTION_KEY)
    record = resolution.get(WORKFLOW_PROPOSAL_KEY) if isinstance(resolution, dict) else None
    return isinstance(record, dict) and record.get("reason_code") == "user_selected_no_workflow"


class ListAvailableWorkflowsTool:
    name = "list_available_workflows"
    description = (
        "List the workflows of this Workspace (the published phased workflows). Each entry reports its key, "
        "title, when to use it and its highest capability class. A workflow never runs inside this chat turn: "
        "propose it to the user, who starts it as a workflow run for a Work item."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        del params
        from ..services.run_admission.phased_catalog import published_phased_workflows

        project_id = context.project_ids[0] if context.project_ids else None
        workflows = [
            {"workflow_key": entry["key"], "title": entry["title"], "when_to_use": entry["when_to_use"],
             "capability_class": entry["capability_class"], "requires_work_item": True,
             "how_to_start": "Propose it; the user starts it as a workflow run for a Work item."}
            for entry in await published_phased_workflows(context.db, project_id=project_id)
        ] if context.db is not None else []
        return {"workflows": workflows, "count": len(workflows)}


class StartWorkflowTool:
    name = "start_workflow"
    description = (
        "Propose one of the workflows from `list_available_workflows` for the user's request, with a short "
        "`reason`. It never starts anything: the user confirms and starts it as a workflow run for a Work item."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        from ..services.run_admission.phased_catalog import RUN_REQUIRED_MESSAGE, phased_key

        workflow_key = str(params.get("workflow_id") or params.get("workflow_key") or "").strip()
        reason = str(params.get("reason") or "").strip()
        if not workflow_key:
            return {"error": "workflow_id is required"}
        if not reason:
            return {"error": "reason is required: state briefly why this workflow fits the request"}
        project_id = context.project_ids[0] if context.project_ids else None
        if context.db is not None and await phased_key(context.db, workflow_key, project_id=project_id):
            # Proposed, never started in the turn (the user starts the run for a Work item).
            return {"status": "needs_confirmation", "reason": WORKFLOW_RUN_REQUIRED, "workflow_key": workflow_key,
                    "proposal_reason": reason, "message": RUN_REQUIRED_MESSAGE.format(key=workflow_key)}
        return {"error": f"Unknown workflow_key '{workflow_key}'; pick one from list_available_workflows.",
                "status": "needs_clarification", "reason": "unknown_key", "workflow_key": workflow_key}


class SelectWorkflowTool:
    """Model-side choice of a published workflow from the workflow catalog by ``workflow_key``.

    This is the meta tool behind the system-prompt workflow catalog (Claude-Code-style progressive
    disclosure). It resolves through the exact same path as the user's composer selection
    (``resolve_explicit_workflow_selection``). A published workflow never runs inside a chat
    turn: the answer is ``needs_confirmation`` (``workflow_run_required``), and the user starts
    the workflow as a run for a Work item. After the user chose "No workflow" it chooses nothing.
    """

    name = "select_workflow"
    description = (
        "Choose a workflow from the workflow catalog in the system prompt when the user request clearly matches a "
        "catalog entry. A workflow never runs inside this chat turn: the answer says how the user starts it as a "
        "workflow run for a Work item. Do not call it when no catalog entry matches (answer directly)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        from ..services.workflow_routing.explicit_selection import resolve_explicit_workflow_selection
        from ..services.workflow_routing.model_catalog import build_model_workflow_catalog

        workflow_key = str(params.get("workflow_key") or "").strip()
        project_id = context.project_ids[0] if context.project_ids else None
        if not workflow_key:
            # Repeating the same key-less call is a live failure mode (four
            # identical attempts, turn produced nothing). The
            # answer escalates from catalog to exact call syntax to an explicit
            # stop instruction instead of inviting another identical retry.
            attempt = _count_keyless_select_workflow_calls(context) + 1
            catalog = await build_model_workflow_catalog(context.db, project_id=project_id)
            response: dict[str, object] = {
                "error": "workflow_key is required; pick one from the workflow catalog.",
                "available_workflows": catalog,
                "keyless_attempt": attempt,
            }
            if attempt >= 2:
                keys = ", ".join(str(entry.get("key") or "") for entry in catalog if entry.get("key"))
                response["required_call_syntax"] = (
                    'select_workflow with arguments {"workflow_key": "<one of: ' + keys + '>"}'
                )
            if attempt >= 3:
                response["next_step"] = (
                    "Do not call select_workflow again without workflow_key. Either call it once with an "
                    "explicit workflow_key argument, or continue without a workflow and answer directly."
                )
            return response
        if _user_selected_no_workflow(context):
            return {
                "status": "user_selected_no_workflow",
                "message": "The user chose to continue without a workflow for this turn; answer directly.",
                "workflow_key": workflow_key,
            }
        resolution = await resolve_explicit_workflow_selection(
            context.db, workflow_key=workflow_key, project_id=project_id
        )
        status = str(resolution.get("status") or "")
        return {
            "error": str(resolution.get("unmatched_reason") or f"Unknown workflow_key '{workflow_key}'."),
            "workflow_key": workflow_key,
            # An archived workflow is a typed denial, not an unknown key; a published workflow
            # starts only as a workflow run for a Work item (propose it to the user).
            **({"status": "denied", "reason": WORKFLOW_ARCHIVED} if status == WORKFLOW_ARCHIVED else {}),
            **({"status": "needs_confirmation", "reason": WORKFLOW_RUN_REQUIRED}
               if status == WORKFLOW_RUN_REQUIRED else {}),
            "available_workflows": await build_model_workflow_catalog(context.db, project_id=project_id),
        }


__all__ = [
    "ListAvailableWorkflowsTool",
    "SelectWorkflowTool",
    "StartWorkflowTool",
]
