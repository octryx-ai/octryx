"""What a run's size class changes at a step: a skipped check, and the class's note for the agent.

Both come from the run's class snapshot (``size_classes`` of its workflow, ``context.size_class``); the engine knows
no step or class by name. A skipped step takes its ``succeeded`` exit with the event ``node_skipped`` naming the class,
so the run's history says what it left out and why (the team sees why a run ran lightly).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..records import record_event
from . import CONTEXT_KEY, class_config, size_of

EVENT_SKIPPED = "node_skipped"
EVENT_KEPT = "node_kept"
UNLESS_UI = "ui_paths"


def _kept_by_change(run: WorkflowRun, node_id: str) -> str:
    """Why a skip with ``"unless_changed": "ui_paths"`` keeps the step: the change touches what a person sees (the
    stacks' ``ui_paths``), or the platform cannot read the change; ``""`` when it skips."""
    from ...engineering_knowledge.stacks import touches_ui
    from ..octryx.system_tests import changed_files

    spec = next((skip for skip in class_config(run).get("skip_nodes") or []
                 if isinstance(skip, dict) and skip.get("node") == node_id), {})
    if spec.get("unless_changed") != UNLESS_UI:
        return ""
    changed = changed_files(dict(run.context or {}).get("device_change"))
    if changed is None:
        return "the change cannot be read, so it may touch the user interface"
    return "the change touches the user interface (stacks' ui_paths)" if touches_ui(changed) else ""


async def skip_entered(db: AsyncSession, run: WorkflowRun, node: Any) -> bool:
    """``True`` (and the event) when the run's class skips the step it just entered; the step's action still does
    what the steps after it need (:func:`platform_actions.action_skipped`)."""
    skips = list(dict(dict(run.context or {}).get(CONTEXT_KEY) or {}).get("skips") or [])
    if node.id not in skips:
        return False
    if kept := _kept_by_change(run, node.id):
        record_event(db, run, EVENT_KEPT, node_id=node.id, detail={"class": size_of(run), "reason": kept})
        return False
    from ..platform_actions import action_skipped

    record_event(db, run, EVENT_SKIPPED, node_id=node.id,
                 detail={"class": size_of(run), "reason": f"class {size_of(run)} skips this step"})
    await action_skipped(db, run, node)
    return True


def agent_facts(run: WorkflowRun) -> dict[str, Any] | None:
    """The class and its note for the agent's contract (``None`` without a note)."""
    note = str(class_config(run).get("agent_note") or "").strip()
    return {"class": size_of(run), "note": note} if note else None


__all__ = ["EVENT_KEPT", "EVENT_SKIPPED", "UNLESS_UI", "agent_facts", "skip_entered"]
