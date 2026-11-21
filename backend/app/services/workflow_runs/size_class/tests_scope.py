"""What the agent's own test runs cover (``"agent_tests": "affected" | "full"``).

Example (class S): the fix phase's Stop refused three times until the agent had run the whole Flutter
suite (66-107 s each), and the pipeline right after ran the same suite again. With ``affected`` the agent runs only
the test files of the confirmed tests and of the code it changed, and the Stop's whole-suite check is advisory: the
pipeline after the phase is the judge. A gate between the phase and the pipeline (the bug flow's ``green``) still
judges the agent's last run: its confirmed tests passed and nothing failed. The schema allows ``affected`` only when
such a pipeline comes after every phase that changes code (:func:`pipeline_later`), so nobody skips the whole suite.
A red pipeline costs a round (with a Flutter system test about 4-5 min), so this pays only while regressions in other
files stay rare; the after-measurement records it.
"""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from . import class_config

AFFECTED, FULL = "affected", "full"


def agent_tests(run: WorkflowRun | None) -> str:
    """``affected`` when the run's class leaves the whole suite to the pipeline after the phase, else ``full``."""
    return AFFECTED if class_config(run).get("agent_tests") == AFFECTED else FULL


def pipeline_later(graph: Any, node_id: str) -> bool:
    """Whether the pipeline step comes after ``node_id`` on its way forward over phases and gates (never loops)."""
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
