"""Claude Code's own sub-agents (the ``Agent`` tool) in one device phase: opt-in per node.

A workflow run's device turn is lean (base context below 10k tokens): the launcher passes Claude Code only the
six tools a phase uses, so the model cannot start a sub-agent. A phase node with ``"subagents": true`` in its
``config`` lets that phase's turn have ``Agent`` as well: the job offer carries ``subagents: true`` and the launcher
adds the tool for that turn. Nothing else changes: every tool call a sub-agent makes runs in the same Claude Code
process, so the platform's PreToolUse hook and ``can_use_tool`` judge it like the main session's (the phase's
tools, path rules and capability class), and its end is a SubagentStop the run records (``stop._child_stop``).

Default off: a node without the key, or with anything but ``true``, keeps the six tools.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

SUBAGENTS_KEY = "subagents"


def node_allows_subagents(node: Any) -> bool:
    """Whether a phase node opted in (``config.subagents`` is exactly ``true``)."""
    config = getattr(node, "config", None)
    return isinstance(config, dict) and config.get(SUBAGENTS_KEY) is True


async def turn_phase(db: AsyncSession, run: WorkflowRun | None) -> Any:
    """The phase node a device turn of ``run`` works: the run's current node, or for a runtime step's turn
    (``workspace.prepare``, the CI pipeline) the phase its agent goes on with (the continuation's ``then_phase``);
    ``None`` without a run or a node.

    epic-delivery enters ``implement`` straight from ``prepare`` and returns to it from a red pipeline inside the
    same turn: judged by the runtime step alone, both turns started without the phase's opt-ins (sub-agents,
    browser)."""
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
    """Whether the phase the turn works (:func:`turn_phase`) opted in; ``False`` without a run or a node."""
    return node_allows_subagents(await turn_phase(db, run))


__all__ = ["SUBAGENTS_KEY", "node_allows_subagents", "run_allows_subagents", "turn_phase"]
