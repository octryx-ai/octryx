"""Claude Code's own sub-agents (the ``Agent`` tool) in one device phase: opt-in per node."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

SUBAGENTS_KEY = "subagents"


def node_allows_subagents(node: Any) -> bool:
    config = getattr(node, "config", None)
    return isinstance(config, dict) and config.get(SUBAGENTS_KEY) is True


async def turn_phase(db: AsyncSession, run: WorkflowRun | None) -> Any:
    if run is None or not run.current_node_id:
        return None
    from ..graph import NODE_PHASE, graph_for_run
    from .continuation_marker import CONTEXT_KEY, THEN_KEY

    nodes = (await graph_for_run(db, run)).nodes
    current = nodes.get(run.current_node_id)
    if current is not None and current.kind == NODE_PHASE:
        return current
    marker = dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
    then = str(marker.get(THEN_KEY) or "") if marker.get("node_id") == run.current_node_id else ""
    return nodes.get(then) if then else current


async def run_allows_subagents(db: AsyncSession, run: WorkflowRun | None) -> bool:
    return node_allows_subagents(await turn_phase(db, run))


__all__ = ["SUBAGENTS_KEY", "node_allows_subagents", "run_allows_subagents", "turn_phase"]
