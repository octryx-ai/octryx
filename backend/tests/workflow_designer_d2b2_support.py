"""Shared helpers for the test_workflow_designer_d2b2_* modules."""

from __future__ import annotations

import copy

from app.services.flow_definitions import validate_flow_definition
from tests.phased_workflow_fixtures import PHASE


def _codes(definition: dict) -> list[str]:
    return [error["code"] for error in validate_flow_definition(definition)["errors"]]


def _edge(edge_id: str, source: str, target: str, when: str | None = None) -> dict:
    return {"id": edge_id, "source_node_id": source, "target_node_id": target, "when": when}


def _outcome(node_id: str, value: str) -> dict:
    return {"id": node_id, "type": "outcome", "config": {"outcome": value}}


def result_definition(*, options: list[str] | None = None, otherwise: bool = False) -> dict:
    """start → agent (ends with fix_needed | no_fix) → condition on its result → two branches."""
    phase = copy.deepcopy(PHASE)
    phase["result_values"] = ["fix_needed", "no_fix"]
    edges = [_edge("e0", "start", "work"), _edge("e1", "work", "pick"), _edge("y", "pick", "fixed", "fix_needed")]
    edges.append(_edge("n", "pick", "blocked", "otherwise") if otherwise else _edge("n", "pick", "blocked", "no_fix"))
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "work", "type": "phase", "label": "Assess", "config": phase},
                  {"id": "pick", "type": "decision",
                   "config": {"source": "work", "options": options or ["fix_needed", "no_fix"]}},
                  _outcome("fixed", "done"), _outcome("blocked", "blocked")],
        "edges": edges,
    }
