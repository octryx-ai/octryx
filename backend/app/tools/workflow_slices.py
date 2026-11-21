"""Run-scoped sub-agent tools of a workflow run phase.

``delegate_slices`` hands the phase's slices to sub-agents (own worktree branch each, the phase's contract, run-
budgeted time) and ``merge_slices`` merges the finished ones into the run's working copy. Both refuse outside a
phase that declares ``sub_agents``; every decision is in ``services/workflow_runs/slices``.
"""

from __future__ import annotations

from typing import Any

from ..models import Session
from ..services.workflow_runs.records import WorkflowRunError
from .context import ToolContext


async def _parent(context: ToolContext) -> Session | None:
    return await context.db.get(Session, context.session_id) if context.db and context.session_id else None


def _refusal(error: WorkflowRunError) -> dict[str, Any]:
    return {"status": "refused", "error": error.code, "message": str(error)}


class DelegateSlicesTool:
    name = "delegate_slices"
    description = ("Delegate this workflow run phase's slices to sub-agents: each slice gets its own worktree branch "
                   "and a sub-agent bound to the phase's contract. Re-delegate a slice with its findings.")

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.workflow_runs.slices.delegate import delegate_slices

        parent = await _parent(context)
        if parent is None:
            return {"status": "refused", "error": "no_session"}
        try:
            result = await delegate_slices(context.db, parent_session=parent, slices=list(params.get("slices") or []))
        except WorkflowRunError as error:
            return _refusal(error)
        await context.db.commit()
        return result


class MergeSlicesTool:
    name = "merge_slices"
    description = ("Merge the finished slices of this workflow run phase into the run's working copy; a conflict is "
                   "reported per slice and loops back through the phase's gate.")

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.workflow_runs.slices.results import merge_slices

        del params
        parent = await _parent(context)
        if parent is None:
            return {"status": "refused", "error": "no_session"}
        try:
            result = await merge_slices(context.db, parent_session=parent)
        except WorkflowRunError as error:
            return _refusal(error)
        await context.db.commit()
        return result


__all__ = ["DelegateSlicesTool", "MergeSlicesTool"]
