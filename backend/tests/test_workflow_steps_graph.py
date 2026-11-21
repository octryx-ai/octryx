"""The Canvas graph adapter of a phased workflow's phase."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.agent.loops.response._loop_workflow_checks import selected_workflow_checks
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.phase_steps_graph import definition_from_graph, definition_graph

SEEDS = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"
FIELDS = ("workflow_id", "workflow_class", "workflow_contract", "tool_policy", "safety_constraints")
KNOWLEDGE_PHASE = {
    "workflow_id": "knowledge_request",
    "workflow_class": "knowledge_request",
    "workflow_contract": {
        "workflow_id": "knowledge_request", "capability_class": "read_only",
        "checks": [{"type": "tool_called", "params": {"tools": ["knowledge_search"]}, "blocking": True},
                   {"type": "citations_present", "blocking": True}],
    },
    "tool_policy": {"allowlist": ["knowledge_search", "knowledge_read"]},
    "safety_constraints": {"diagnosis_mode": True},
}


def _phase_payloads() -> list[dict]:
    return [
        {field: node["config"].get(field) for field in FIELDS}
        for seed in json.loads(SEEDS.read_text())
        for node in seed["definition"]["nodes"]
        if node.get("type") == "phase"
    ]


def _chat_checks(payload: dict) -> tuple[str, list]:
    """What a workflow run phase's turn enforces at turn end for this payload."""
    resolution = {"source": "db", "status": "matched", "selection_source": "workflow_run",
                  "workflow_key": "k", "workflow_id": payload["workflow_id"],
                  "workflow_contract": payload["workflow_contract"], "tool_policy": payload["tool_policy"]}
    return selected_workflow_checks({ROUTING_RESOLUTION_KEY: resolution})


@pytest.mark.parametrize("payload", _phase_payloads(), ids=lambda payload: payload["workflow_id"])
def test_definition_to_graph_to_definition_is_identity(payload):
    graph = definition_graph(payload)
    assert definition_from_graph(payload, graph) == payload
    assert definition_from_graph(payload, json.loads(json.dumps(graph))) == payload  # survives the wire


def test_the_graph_reads_start_steps_checks_result_with_modes_approvals_and_allowed_tools():
    payload = {"workflow_contract": {"capability_class": "change", "source_steps": [
        {"tool": "knowledge_search", "evidence_label": "sources"},
        {"tool": "write_file", "mode": "guided"},
    ], "checks": [{"type": "judge", "blocking": True}, {"type": "citations_present", "blocking": True}]},
        "tool_policy": {"allowlist": ["knowledge_search"]}}

    graph = definition_graph(payload, tool_requires_approval=lambda name: name == "write_file")

    kinds = [(node["kind"], node.get("tool") or node.get("type") or node.get("reason", "")) for node in graph["nodes"]]
    assert kinds == [("start", ""), ("approval", "capability_class"), ("step", "knowledge_search"),
                     ("approval", "write_file"), ("step", "write_file"), ("check", "judge"),
                     ("check", "citations_present"), ("result", "")]
    steps = [node for node in graph["nodes"] if node["kind"] == "step"]
    assert [(step["mode"], step["mode_explicit"], step["allowed"]) for step in steps] == [
        ("strict", False, True), ("guided", True, False)]
    assert [node["blocking"] for node in graph["nodes"] if node["kind"] == "check"] == [False, True]
    assert len(graph["edges"]) == len(graph["nodes"]) - 1


def test_a_canvas_edit_enforces_exactly_like_the_same_table_edit():
    seed = deepcopy(KNOWLEDGE_PHASE)
    # Table: the JSON editor adds a strict first step and turns the citation check into a reminder.
    table = deepcopy(seed)
    table["workflow_contract"]["source_steps"] = [{"tool": "knowledge_search", "evidence_label": "sources",
                                                   "mode": "strict"}]
    table["workflow_contract"]["checks"][1]["blocking"] = False
    # Canvas: the same edit on the graph's nodes.
    graph = definition_graph(seed)
    nodes = graph["nodes"]
    first_check = next(index for index, node in enumerate(nodes) if node["kind"] == "check")
    nodes.insert(first_check, {"id": "new", "kind": "step",
                               "step": {"tool": "knowledge_search", "evidence_label": "sources", "mode": "strict"}})
    nodes[first_check + 2]["check"]["blocking"] = False

    canvas = definition_from_graph(seed, graph)

    assert canvas == table
    assert _chat_checks(canvas) == _chat_checks(table)
    _key, checks = _chat_checks(canvas)
    assert [(check["type"], check.get("blocking")) for check in checks][:2] == [
        ("tool_called", True), ("citations_present", False)]


def test_derived_nodes_are_ignored_and_a_malformed_node_is_refused():
    from app.services.workflow_runs.phase_steps_graph import GraphShapeError

    payload = {"workflow_contract": {}}
    graph = {"nodes": [{"kind": "start"}, {"kind": "approval"}, {"kind": "result"}]}
    assert definition_from_graph(payload, graph) == payload
    with pytest.raises(GraphShapeError) as error:
        definition_from_graph(payload, {"nodes": [{"kind": "step"}]})
    assert error.value.code == "invalid_graph_node"
