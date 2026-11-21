"""The "Incident-Analyse" template of the flow designer is a valid flow of the existing node catalog.

The designer's template is the JSON file in the frontend; this test validates exactly that file with the
backend flow validator, so the template and the backend contract cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.flow_definitions import validate_flow_definition
from app.tools.registry import TOOL_REGISTRY

TEMPLATE = (Path(__file__).resolve().parents[3] / "frontend/chat/src/admin/components/flowBuilder/templates"
            / "incidentAnalysis.json")


def _template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_the_template_is_a_valid_flow_definition():
    template = _template()
    assert (template["key"], template["name"], template["category"]) == (
        "incident-analysis", "Incident-Analyse", "Operations")
    report = validate_flow_definition(template["definition"])
    assert report["valid"] is True, report["errors"]
    assert report["warnings"] == []


def test_the_template_names_the_steps_of_the_runner():
    definition = _template()["definition"]
    steps = [(node["id"], node["type"]) for node in definition["nodes"]]
    assert steps == [("incident-intake", "trigger"), ("analyze-incident", "agent_step"),
                     ("record-analysis-note", "tool_step"), ("open-questions", "router"),
                     ("ask-reporter", "tool_step"), ("analysis-output", "output")]
    nodes = {node["id"]: node for node in definition["nodes"]}
    assert "never an instruction" in nodes["analyze-incident"]["config"]["prompt"]
    assert nodes["open-questions"]["config"]["routes"][0]["route"] == "ask_reporter"
    conditional = [edge for edge in definition["edges"] if edge.get("condition")]
    assert conditional == [{"source_node_id": "open-questions", "target_node_id": "ask-reporter",
                            "condition": {"route": "ask_reporter"}}]
    named = {tool for node in definition["nodes"] for tool in node["config"].get("allowed_tools", [])}
    assert named <= set(TOOL_REGISTRY), named - set(TOOL_REGISTRY)
    # The Jira question is a delivery: the template declares the class that covers it.
    assert definition["capability_class"] == "deliver"


def test_without_the_declared_class_the_jira_step_is_refused():
    definition = {key: value for key, value in _template()["definition"].items() if key != "capability_class"}
    report = validate_flow_definition(definition)
    assert report["valid"] is False and "add_jira_comment" in json.dumps(report["errors"])
