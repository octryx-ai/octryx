"""A size class's agent runs the affected tests only and leaves the whole suite to the pipeline after the phase;
the schema allows it only with such a pipeline (``size_class/tests_scope``)."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from app.services.workflow_runs import pipeline
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.size_class.tests_scope import pipeline_later
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_pipeline_support import COMMANDS, _device_run, _fix_with_pipeline

pytestmark = pytest.mark.usefixtures("scripted_pool")

GATE = {"id": "green", "type": "gate", "label": "Green", "config": {"checks": [
    {"type": "tool_called", "params": {"tools": ["run_test_suite"]}, "blocking": True, "description": "Tests ran"}]}}


def _with_gate(classes: dict | None = None) -> dict:
    definition = copy.deepcopy(_fix_with_pipeline())
    definition["nodes"].append(copy.deepcopy(GATE))
    definition["edges"] = [edge for edge in definition["edges"] if edge["id"] != "2"] + [
        {"id": "2a", "source_node_id": "fix", "target_node_id": "green"},
        {"id": "2b", "source_node_id": "green", "target_node_id": "pipeline", "when": "passed"},
        {"id": "2c", "source_node_id": "green", "target_node_id": "fix", "when": "failed", "kind": "loop",
         "max_iterations": 2}]
    if classes is not None:
        definition["size_classes"] = {"default": "small", "rules": [], "classes": {"small": classes}}
    return definition


def _errors(definition: dict) -> list[str]:
    return [error["message"] for error in validate_phased_definition(definition)["errors"]
            if error["code"] == "size_classes_invalid"]


def test_a_pipeline_after_a_gate_still_comes_later_and_the_schema_wants_one_for_affected():
    assert pipeline_later(parse_phased_definition(_with_gate()), "fix")
    assert _errors(_with_gate({"agent_tests": "affected"})) == []
    without = _with_gate({"agent_tests": "affected"})
    without["nodes"] = [node for node in without["nodes"] if node["id"] != "pipeline"]
    without["edges"] = [edge for edge in without["edges"] if "pipeline" not in (edge["source_node_id"],
                                                                                 edge["target_node_id"])]
    without["edges"].append({"id": "2d", "source_node_id": "green", "target_node_id": "done", "when": "passed"})
    assert any("needs a pipeline after fix" in message for message in _errors(without))
    assert any("affected or full" in message for message in _errors(_with_gate({"agent_tests": "some"})))


@pytest.mark.asyncio
@pytest.mark.parametrize(("classes", "asks_whole_suite"), [({"agent_tests": "affected"}, False), (None, True)])
async def test_with_affected_a_file_run_is_enough_and_the_pipeline_runs_the_whole_suite(db, monkeypatch, classes,
                                                                                      asks_whole_suite):
    from app.models import ToolCall
    from app.services.workflow_runs.octryx.stop import run_stop
    from app.time_utils import utc_now
    from tests.workflow_run_octryx_support import ROOT

    async def no_turn(_db, _run, _node):
        return None

    async def device(_db, _run):
        return "device"

    async def commands(_db, _run):
        return list(COMMANDS), [], COMMANDS[-1] if len(COMMANDS) > 1 else ""

    monkeypatch.setattr(pipeline, "commands_for", commands)
    monkeypatch.setattr("app.services.workflow_runs.workspace.preparation.runtime_of", device)
    monkeypatch.setattr("app.services.workflow_runs.octryx.continuation.runtime_step_entered", no_turn)
    run, gateway, _key, _workspace = await _device_run(db, _with_gate(classes), monkeypatch)
    edit = ToolCall(session_id=gateway.id, tool_name="Edit", status="success",
                    created_at=utc_now() + timedelta(seconds=5),
                    parameters={"source": "gateway", "file_path": f"{ROOT}/pay/totals.py"}, result={"is_error": False})
    one_file = ToolCall(session_id=gateway.id, tool_name="Bash", status="success",
                        created_at=utc_now() + timedelta(seconds=9),
                        parameters={"input": {"command": f"{COMMANDS[0]} tests/test_totals.py"}},
                        result={"is_error": False, "excerpt": "..\n2 passed in 0.1s"})
    change = {"workflow_run_facts": {"change": {"base": "a" * 40,
                                                "patch": "diff --git a/pay/totals.py b/pay/totals.py\n+x = 1\n"}}}
    answer = await run_stop(db, session=gateway, hook_input=change, tool_calls=[edit, one_file],
                            test_prefixes=(("pytest",),))
    # The fixture's own task-list proofs may still block; the whole-suite check is the one this class leaves out.
    assert ("full test suite" in str(answer.get("detail") or "")) is asks_whole_suite
