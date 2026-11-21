"""A push that agent work reaches without an independent review is warned about.

A device run pushes only the change the reviewer reviewed, so a workflow whose agent work reaches the push without a
review stops there for safety; the designer must say so instead of calling the workflow valid.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.workflow_runs.graph_validation import validate_phased_definition


def _spec_workflow(with_review: bool) -> dict:
    nodes = [{"id": "start", "type": "start"},
             {"id": "spec", "type": "phase", "config": {"agent": "engineer", "workflow_contract": {
                 "capability_class": "change", "checks": [{"type": "tool_called", "params": {"tools": ["Write"]}}]}}},
             {"id": "push", "type": "platform_action", "config": {"action": "scm.push"}},
             {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
             {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}]
    edges = [{"id": "e1", "source_node_id": "start", "target_node_id": "spec"},
             {"id": "e3", "source_node_id": "push", "target_node_id": "done", "when": "succeeded"},
             {"id": "e4", "source_node_id": "push", "target_node_id": "blocked", "when": "failed"}]
    if with_review:
        nodes.append({"id": "independent_review", "type": "review", "config": {"phase": "spec"}})
        edges += [{"id": "e2", "source_node_id": "spec", "target_node_id": "independent_review"},
                  {"id": "e2b", "source_node_id": "independent_review", "target_node_id": "push"}]
    else:
        edges.append({"id": "e2", "source_node_id": "spec", "target_node_id": "push"})
    return {"execution_kind": "phased", "nodes": nodes, "edges": edges}


def _codes(definition: dict) -> set[str]:
    report = validate_phased_definition(definition)
    assert "push_without_review" not in {error["code"] for error in report["errors"]}  # a server run may push
    return {warning["code"] for warning in report["warnings"]}


def test_a_push_after_agent_work_needs_an_independent_review():
    assert "push_without_review" in _codes(_spec_workflow(with_review=False))
    assert "push_without_review" not in _codes(_spec_workflow(with_review=True))


def test_the_seeded_workflows_keep_validating_on_this_rule():
    seeds = json.loads((Path(__file__).parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json")
                       .read_text(encoding="utf-8"))
    items = seeds if isinstance(seeds, list) else list(seeds.get("workflows") or seeds.values())
    definitions = [item.get("definition") or item.get("definition_json") or item for item in items
                   if isinstance(item, dict)]
    checked = [d for d in definitions if isinstance(d, dict) and d.get("nodes")]
    assert checked
    for definition in checked:
        assert "push_without_review" not in _codes(definition)
