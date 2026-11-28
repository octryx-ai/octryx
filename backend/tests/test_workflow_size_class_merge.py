"""A size class lays one phase into a later one (``merge``): the skipped steps' duties wait for the merged phase,
and the schema allows it only where it is safe and with ``red_on_base``."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import WorkflowRun, WorkflowRunEvent
from app.services.workflow_runs.graph import graph_for_run
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.records import start_run
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


def _phase(text: str, **extra) -> dict:
    config = copy.deepcopy(PHASE)
    config["workflow_contract"]["when_to_use"] = text
    return {**config, **extra}


def _definition(classes: dict) -> dict:
    write = _phase("Write the failing test.", output="reproduction",
                   tool_policy={"allowlist": ["knowledge_search", "submit_reproduction"], "denylist": []})
    write["workflow_contract"]["path_rules"] = {"write": ["tests/**"]}
    write["workflow_contract"]["checks"] = [{"type": "tool_called", "params": {"tools": ["submit_reproduction"]},
                                             "blocking": True, "description": "The reproduction was submitted"}]
    make = _phase("Make it pass.")
    make["workflow_contract"]["path_rules"] = {"protect_confirmed_tests": True}
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "go", "type": "start"},
                  {"id": "write", "type": "phase", "label": "Write", "config": write},
                  {"id": "look", "type": "platform_action", "config": {"action": "hands_on.run", "mode": "reproduce"}},
                  {"id": "judge", "type": "gate", "config": {"checks": [
                      {"type": "tool_called", "params": {"tools": ["x"]}, "blocking": True, "description": "x"}]}},
                  {"id": "make", "type": "phase", "label": "Make", "config": make},
                  {"id": "fine", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "e1", "source_node_id": "go", "target_node_id": "write"},
                  {"id": "e2", "source_node_id": "write", "target_node_id": "look"},
                  {"id": "e3", "source_node_id": "look", "target_node_id": "judge", "when": "succeeded"},
                  {"id": "e4", "source_node_id": "look", "target_node_id": "write", "when": "failed", "kind": "loop",
                   "max_iterations": 2},
                  {"id": "e5", "source_node_id": "judge", "target_node_id": "make", "when": "passed"},
                  {"id": "e6", "source_node_id": "judge", "target_node_id": "write", "when": "failed", "kind": "loop",
                   "max_iterations": 2},
                  {"id": "e7", "source_node_id": "make", "target_node_id": "fine"}],
        "size_classes": {"default": "small", "rules": [], "classes": {"small": classes, "big": {}}},
    }


MERGE = {"merge": {"write": "make"}, "red_on_base": True}


@pytest.mark.asyncio
async def test_the_run_starts_in_the_later_phase_which_carries_both_definitions(db):
    workspace_id = await run_workspace(db, await admin_user(db))
    run = await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, _definition(MERGE)),
                          project_id=workspace_id)
    assert (run.status, run.current_node_id) == ("running", "make")
    skipped = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "node_skipped"))).scalars().all()
    assert [(event.node_id, event.detail["merged_into"]) for event in skipped] == [
        ("write", "make"), ("look", "make"), ("judge", "make")]
    make = (await graph_for_run(db, run)).nodes["make"].config
    assert make["output"] == "reproduction" and "submit_reproduction" in make["tool_policy"]["allowlist"]
    assert make["workflow_contract"]["when_to_use"] == "Write the failing test. Then, in the same turn: Make it pass."
    assert make["workflow_contract"]["path_rules"] == {"protect_confirmed_tests": True, "write_tests": True}


@pytest.mark.asyncio
async def test_a_skipped_steps_duty_waits_for_the_merged_phases_output_and_runs_once(db, monkeypatch):
    from app.services.workflow_runs.hands_on import reproduce
    from app.services.workflow_runs.size_class.merge import CONTEXT, output_recorded

    calls = []

    async def confirm(_db, run):
        calls.append(run.id)

    monkeypatch.setattr(reproduce, "confirm_automatically", confirm)
    workspace_id = await run_workspace(db, await admin_user(db))
    run = await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, _definition(MERGE)),
                          project_id=workspace_id)
    assert calls == [] and run.context[CONTEXT]["deferred"] == ["look"]
    graph = await graph_for_run(db, run)
    await output_recorded(db, run, graph, graph.nodes["make"])
    await output_recorded(db, run, graph, graph.nodes["make"])
    assert calls == [run.id]


@pytest.mark.asyncio
async def test_without_the_merge_the_run_starts_in_the_first_phase_as_before(db):
    workspace_id = await run_workspace(db, await admin_user(db))
    run = await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, _definition({})),
                          project_id=workspace_id)
    assert run.current_node_id == "write" and isinstance(run, WorkflowRun)


@pytest.mark.parametrize(("classes", "says"), [
    ({"merge": {"write": "make"}}, "needs red_on_base"),
    ({"merge": {"write": "fine"}, "red_on_base": True}, "needs two phases"),
    ({"merge": {"make": "write"}, "red_on_base": True}, "needs two phases"),
    ({"merge": "make", "red_on_base": True}, "maps a phase"),
])
def test_a_merge_the_schema_cannot_keep_safe_is_refused(classes, says):
    errors = [error["message"] for error in validate_phased_definition(_definition(classes))["errors"]
              if error["code"] == "size_classes_invalid"]
    assert any(says in message for message in errors), errors


def test_the_shipped_bug_flows_small_class_fixes_inside_one_phase_with_its_test_proven_on_the_base():
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from app.services.workflow_runs.graph import parse_phased_definition
    from app.services.workflow_runs.size_class.merge import merged_graph

    seeds = json.loads(Path("app/services/workflow_runs/seeds/phased_workflows.json").read_text())
    flows = seeds if isinstance(seeds, list) else seeds.get("workflows") or list(seeds.values())
    definition = next(flow for flow in flows if isinstance(flow, dict) and flow.get("key") == "bug-fix-reproduction")
    definition = definition.get("definition", definition)
    classes = definition["size_classes"]["classes"]
    assert classes["S"]["merge"] == {"reproduce": "fix"} and classes["S"]["red_on_base"] is True
    run = SimpleNamespace(context={"size_class": {"class": "S", "classes": classes}})
    fix = merged_graph(parse_phased_definition(definition), run).nodes["fix"].config
    assert fix["output"] == "reproduction" and "submit_reproduction" in fix["tool_policy"]["allowlist"]
    assert fix["workflow_contract"]["path_rules"]["protect_confirmed_tests"] is True
    assert "Then, in the same turn:" in fix["workflow_contract"]["when_to_use"]


@pytest.mark.asyncio
async def test_a_steps_turn_goes_on_with_the_phase_the_merge_leads_to(monkeypatch):
    from types import SimpleNamespace

    from app.services.workflow_runs.graph import parse_phased_definition
    from app.services.workflow_runs.octryx.continuation import _following_phase

    definition = _definition(MERGE)
    graph = parse_phased_definition(definition)

    async def the_graph(_db, _run):
        return graph

    monkeypatch.setattr("app.services.workflow_runs.graph.graph_for_run", the_graph)
    merged = SimpleNamespace(context={"size_class": {"class": "small", "classes": definition["size_classes"]["classes"]}})
    plain = SimpleNamespace(context={})
    assert await _following_phase(None, merged, graph.nodes["look"]) == "make"
    assert await _following_phase(None, plain, graph.nodes["look"]) == "write"
