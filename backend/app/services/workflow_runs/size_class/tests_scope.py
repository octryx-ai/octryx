"""What the agent's own test runs cover (``"agent_tests": "affected" | "full"``)."""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from . import class_config

AFFECTED, FULL = "affected", "full"


def agent_tests(run: WorkflowRun | None) -> str:
    return AFFECTED if class_config(run).get("agent_tests") == AFFECTED else FULL


def pipeline_later(graph: Any, node_id: str) -> bool:
    from ..graph import EDGE_LOOP, NODE_GATE, NODE_PARALLEL, NODE_PHASE, NODE_PLATFORM_ACTION
    from ..pipeline import ACTION

    nodes = dict(getattr(graph, "nodes", None) or {})
    edges = [edge for edge in getattr(graph, "edges", None) or [] if getattr(edge, "kind", None) != EDGE_LOOP]
    seen, frontier = {node_id}, [node_id]
    while frontier:
        source = frontier.pop()
        for edge in edges:
            target = nodes.get(edge.target) if edge.source == source else None
            if target is None or edge.target in seen:
                continue
            if target.kind == NODE_PLATFORM_ACTION and target.config.get("action") == ACTION:
                return True
            if target.kind in (NODE_PHASE, NODE_PARALLEL, NODE_GATE):
                seen.add(edge.target)
                frontier.append(edge.target)
    return False


__all__ = ["AFFECTED", "FULL", "agent_tests", "pipeline_later"]
