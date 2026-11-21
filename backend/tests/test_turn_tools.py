"""A run turn's built-in tools and its system prompt are data, and a phase turn lists only the run tools it uses
(system prompt and tool definitions otherwise take a large share of every call's tokens)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.devices.job_offer import offer_body
from app.services.mcp_knowledge_phase import hidden_in_phase
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.octryx.turn_tools import builtin_tools, device_system_prompt
from app.services.workflow_runs.run_texts import run_text


def _run(classes: dict) -> SimpleNamespace:
    return SimpleNamespace(context={"size_class": {"class": "small", "classes": {"small": classes}}})


def test_a_phases_own_tools_win_over_its_size_class_and_neither_keeps_the_launchers_default():
    phase = SimpleNamespace(config={"builtin_tools": ["Read", "Edit", "Read"]})
    run = _run({"builtin_tools": ["Read", "Bash"]})
    assert builtin_tools(run, phase) == ["Read", "Edit"]
    assert builtin_tools(run, SimpleNamespace(config={})) == ["Read", "Bash"]
    assert builtin_tools(_run({}), SimpleNamespace(config={"builtin_tools": []})) is None


def test_the_offer_carries_the_tools_and_the_catalog_prompt():
    job = SimpleNamespace(id="j", turn_id="t", turn_prompt="go", folder="/x", profile="seat", turn_model="",
                          workspace_id="w", session_id="s", policy_decision_id=None, resume_claude_session_id=None,
                          claude_session_id=None)
    body = offer_body(job, limits={}, builtin_tools=["Read", "Bash"], system_prompt="Do the phase.")
    assert (body["builtin_tools"], body["system_prompt"]) == (["Read", "Bash"], "Do the phase.")
    assert "builtin_tools" not in offer_body(job, limits={}) and "system_prompt" not in offer_body(job, limits={})


@pytest.mark.asyncio
async def test_the_device_system_prompt_is_a_catalog_text_that_no_longer_sends_the_agent_to_the_status_first(db):
    text = run_text("device.system_prompt")
    assert "comes with the prompt" in text and "only if it is missing" in text
    assert await device_system_prompt(db, None) == ""


def test_a_phase_turn_lists_its_tools_and_the_run_tools_it_uses_only():
    names = ["knowledge_search", "submit_reproduction", "workflow_run_status", "workflow_action_request",
             "workflow_decide", "workflow_select", "workflow_confirm", "workflow_catalog"]
    assert hidden_in_phase(names, {"knowledge_search"}) == {
        "submit_reproduction", "workflow_decide", "workflow_select", "workflow_confirm", "workflow_catalog"}


def test_the_bug_flows_small_and_medium_classes_start_without_sub_agents_and_the_schema_checks_the_list():
    seeds = json.loads(Path("app/services/workflow_runs/seeds/phased_workflows.json").read_text())
    flows = seeds if isinstance(seeds, list) else seeds.get("workflows") or list(seeds.values())
    definition = next(flow for flow in flows if isinstance(flow, dict) and flow.get("key") == "bug-fix-reproduction")
    definition = definition.get("definition", definition)
    classes = definition["size_classes"]["classes"]
    for name in ("S", "M"):
        assert "Agent" not in classes[name]["builtin_tools"] and "Bash" in classes[name]["builtin_tools"]
    broken = json.loads(json.dumps(definition))
    broken["size_classes"]["classes"]["S"]["builtin_tools"] = "Read"
    messages = [error["message"] for error in validate_phased_definition(broken)["errors"]
                if error["code"] == "size_classes_invalid"]
    assert any("builtin_tools" in message for message in messages)
