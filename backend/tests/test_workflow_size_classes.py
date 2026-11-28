"""A workflow's ``size_classes`` block is data the engine evaluates generically."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import WorkflowRun
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.size_class import classify_at_start, escalate, size_of
from app.services.workflow_runs.size_class.rules import first_match
from app.services.workflow_runs.size_class.schema import size_class_errors
from tests.phased_workflow_fixtures import PHASE

SYNTHETIC = {
    "execution_kind": "phased",
    "nodes": [{"id": "begin", "type": "start"},
              {"id": "craft", "type": "phase", "label": "Craft", "config": copy.deepcopy(PHASE)},
              {"id": "try_it", "type": "platform_action", "config": {"action": "hands_on.run"}},
              {"id": "ship", "type": "platform_action", "config": {"action": "scm.push"}},
              {"id": "end", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "stuck", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "a", "source_node_id": "begin", "target_node_id": "craft"},
              {"id": "b", "source_node_id": "craft", "target_node_id": "try_it"},
              {"id": "c", "source_node_id": "try_it", "target_node_id": "ship", "when": "succeeded"},
              {"id": "again", "source_node_id": "try_it", "target_node_id": "craft", "when": "failed", "kind": "loop",
               "max_iterations": 4},
              {"id": "d", "source_node_id": "ship", "target_node_id": "end", "when": "succeeded"},
              {"id": "e", "source_node_id": "ship", "target_node_id": "stuck", "when": "failed"}],
    "size_classes": {
        "default": "big",
        "rules": [{"class": "tiny", "when": {"labels_any": ["quick"], "criteria_max": 1}}],
        "classes": {"tiny": {"session": "shared", "skip_nodes": [{"node": "try_it", "unless_labels": ["look"]}],
                             "max_rounds": {"again": 1}, "escalate_to": "big", "agent_note": "Keep it small."},
                    "big": {"session": "per_phase"}}},
}


def _codes(definition: dict) -> list[str]:
    return [error["message"] for error in validate_phased_definition(definition)["errors"]
            if error["code"] == "size_classes_invalid"]


def _with(**changes) -> dict:
    definition = copy.deepcopy(SYNTHETIC)
    definition["size_classes"]["classes"]["tiny"].update(changes)
    return definition


def test_a_synthetic_workflow_with_its_own_names_validates_and_classifies():
    assert _codes(SYNTHETIC) == []
    block = SYNTHETIC["size_classes"]
    quick = SimpleNamespace(issue_type="chore", title="t", description="- one", labels_json=["Quick"])
    assert first_match(block, quick) == ("tiny", 1, "labels_any ['quick']; criteria_max 1")
    assert first_match(block, SimpleNamespace(labels_json=["quick"], description="- a\n- b")) == (
        "big", 0, "no rule matched")


@pytest.mark.parametrize(("change", "says"), [
    ({"skip_nodes": [{"node": "ship"}]}, "'ship' cannot be skipped"),
    ({"skip_nodes": [{"node": "nowhere"}]}, "does not have"),
    ({"max_rounds": {"b": 1}}, "max_rounds"),
    ({"escalate_to": "huge"}, "escalate_to"),
    ({"session": "sometimes"}, "session"),
    ({"context_cap_tokens": 0}, "context_cap_tokens"),
    ({"colour": "red"}, "takes"),
    ({"phase_change": "sometimes"}, "phase_change"),
    ({"red_on_base": "yes"}, "red_on_base is true or false"),
    ({"session": "per_phase", "phase_change": "same_turn"}, "with session shared"),
])
def test_a_wrong_block_is_refused_with_a_clear_text(change, says):
    [message] = _codes(_with(**change))
    assert says in message


def test_a_rule_or_an_escalation_cycle_that_cannot_work_is_refused():
    definition = copy.deepcopy(SYNTHETIC)
    definition["size_classes"]["rules"].append({"class": "medium", "when": {}})
    assert "rule 2" in _codes(definition)[0]
    definition = copy.deepcopy(SYNTHETIC)
    definition["size_classes"]["classes"]["big"]["escalate_to"] = "tiny"
    assert "lead back" in _codes(definition)[0]
    no_exit = copy.deepcopy(SYNTHETIC)
    no_exit["edges"] = [edge for edge in no_exit["edges"] if edge["id"] != "c"]
    errors = size_class_errors(no_exit["size_classes"], parse_phased_definition(no_exit))
    assert any("no 'succeeded' exit" in error["message"] for error in errors)


def _seed(key: str) -> dict:
    path = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"
    return next(item["definition"] for item in json.loads(path.read_text()) if item["key"] == key)


OE72 = SimpleNamespace(issue_type="bug", title="Mahlgrad startet bei 0.0 statt 15", labels_json=[],
                       description="Steps:\n1. Open the app, add grinder M1.\nExpected: 15.\nActual: 0.0.")
OE76 = SimpleNamespace(issue_type="task", title="Onboarding S2: Infoseiten mit Fortschritt und Navigation",
                       labels_json=[], description="Acceptance criteria:\n- 1. a\n- 2. b\n- 3. c\n- 4. d\n- 5. e\n"
                                                   "- 6. f\n\nBuilds on: Onboarding S1: Erststart-Flag und Routing")


@pytest.mark.asyncio
@pytest.mark.parametrize(("key", "item", "expected", "skips"), [
    ("bug-fix-reproduction", SimpleNamespace(**{**vars(OE72), "components_json": ["grinder-settings"]}), "S",
     ["repro_check", "hands_on"]),
    # Without labels and components there is no structure to judge by, so M, never the lightest class.
    ("bug-fix-reproduction", OE72, "M", []),
    ("bug-fix-reproduction", SimpleNamespace(**{**vars(OE72), "labels_json": ["ui-visible"]}), "S", ["repro_check"]),
    ("bug-fix-reproduction", SimpleNamespace(**{**vars(OE72), "labels_json": ["full-flow"]}), "L", []),
    # Risk comes from labels and components, not from the prose ("no dependencies" would make a bug L).
    ("bug-fix-reproduction", SimpleNamespace(**{**vars(OE72), "title": "Login fails after password reset",
                                                "labels_json": ["auth"]}), "L", []),
    ("epic-delivery", OE76, "M", []),
    ("epic-delivery", SimpleNamespace(issue_type="task", title="Show the version", labels_json=[],
                                      components_json=["about"], description="- About shows it"), "S", ["hands_on"]),
    ("spec-writing", SimpleNamespace(issue_type="epic", title="Onboarding", labels_json=[], description=""), "M", []),
])
async def test_the_shipped_seeds_carry_todays_classes(monkeypatch, key, item, expected, skips):
    import app.services.workflow_runs.size_class as module

    monkeypatch.setattr(module, "record_event", lambda *_args, **_kwargs: None)
    definition = _seed(key)
    assert validate_phased_definition(definition)["valid"], validate_phased_definition(definition)["errors"]
    run = WorkflowRun(workflow_key=key, context={})
    assert await classify_at_start(None, run, definition, item) == expected
    assert run.context["size_class"]["skips"] == skips


class _Db:
    def __init__(self, runs: dict):
        self.runs = runs

    async def get(self, _model, key):
        return self.runs.get(key)


@pytest.mark.asyncio
async def test_a_run_continuing_a_chain_started_without_classes_takes_none_and_escalation_follows_the_block(
        monkeypatch):
    import app.services.workflow_runs.size_class as module

    events = []
    monkeypatch.setattr(module, "record_event", lambda _db, _run, kind, **kwargs: events.append((kind, kwargs)))
    old = WorkflowRun(id="877e2a8e", context={})
    story = WorkflowRun(workflow_key="x", context={"epic_chain": {"after_run": "877e2a8e"}})
    assert await classify_at_start(_Db({"877e2a8e": old}), story, SYNTHETIC, OE72) == ""
    assert size_of(story) == "" and events[-1][1]["detail"]["class"] is None

    quick = SimpleNamespace(issue_type="chore", title="t", description="", labels_json=["quick"])
    run = WorkflowRun(workflow_key="x", context={})
    assert await classify_at_start(_Db({}), run, SYNTHETIC, quick) == "tiny"
    assert run.context["size_class"]["skips"] == ["try_it"]
    assert escalate(None, run, cause="loop_limit:again") == "big" and escalate(None, run, cause="again") == ""
    assert run.context["size_class"]["skips"] == [] and events[-1][1]["detail"] == {
        "from": "tiny", "to": "big", "cause": "loop_limit:again", "skips": []}


def test_the_watch_view_says_the_class_the_rule_and_what_it_skips():
    from app.models import WorkflowRunEvent
    from app.services.attention.event_text import event_text

    classified = WorkflowRunEvent(kind="size_classified", detail={
        "class": "S", "rule": 3, "matched": "issue_type_in ['bug']", "skips": ["repro_check", "hands_on"]})
    assert event_text(classified, {})[0] == "Class S by rule 3: issue_type_in ['bug']; skips repro_check, hands_on"
    raised = WorkflowRunEvent(kind="size_escalated", detail={"from": "S", "to": "M", "cause": "loop_limit:x",
                                                             "skips": []})
    assert event_text(raised, {})[0] == "Class raised from S to M (loop_limit:x)"
