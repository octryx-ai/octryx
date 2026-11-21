"""Team delivery: the coordinate phase writes the task list with a role per item, each role phase
builds only its items, the pipeline after the last role judges the earlier ones too, and the decision revises only on
a high finding."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.workflow_runs import pipeline
from app.services.workflow_runs.auto_accept import accept_reason
from app.services.workflow_runs.graph import PhasedNode, parse_phased_definition
from app.services.workflow_runs.phase_contract import phase_definition
from app.services.workflow_runs.phase_marker import RUN_PHASE_CONTRACT_KEY
from app.services.workflow_runs.task_list import for_roles, parse, phase_roles, render, run_task_list

ANSWER = """Contract written to docs/stories/MC-3.md.

Task list:
T1. [backend] GET /api/recipes searches names | proof: tests/test_search.py::test_text_search
T2. [frontend] Dish cards in a grid | proof: tests/system/test_cards.py::test_cards
T3. [test, frontend] Empty state text in every language | proof: tests/system/test_cards.py::test_empty
T4. Sample corpus of 20 dishes | proof: tests/test_corpus.py::test_corpus
"""
TEST_ENV = {"test": "pytest -q"}


def test_the_role_tag_is_parsed_and_an_untagged_item_belongs_to_every_role():
    items = parse(ANSWER)
    assert [item.get("roles") for item in items] == [["backend"], ["frontend"], ["test", "frontend"], None]
    assert items[1]["text"] == "Dish cards in a grid" and items[1]["proof"] == "tests/system/test_cards.py::test_cards"
    assert [item["id"] for item in for_roles(items, ["frontend"])] == ["T2", "T3", "T4"]
    assert [item["id"] for item in for_roles(items, ["backend"])] == ["T1", "T4"]
    assert [item["id"] for item in for_roles(items, [])] == ["T1", "T2", "T3", "T4"]
    assert phase_roles({"tasks": "Frontend"}) == ["frontend"] and phase_roles({}) == []
    assert render(items[:1]) == "T1. [backend] GET /api/recipes searches names | proof: tests/test_search.py::test_text_search"


def test_the_coordinate_answer_is_preferred_over_the_readiness_answer():
    readiness = "Task list:\nT1. Old item | proof: tests/test_old.py::test_old\n"
    run = SimpleNamespace(context={"answers": {"readiness": readiness, "coordinate": ANSWER}})
    assert run_task_list(run)[0]["text"] == "Old item"  # unchanged without a preference: ticket delivery
    assert len(run_task_list(run, ("coordinate",))) == 4


def _run(**context):
    return SimpleNamespace(id="r1", work_item_id=None, node_state={"iteration": 1}, workflow_kind="phased",
                           context={"task_list": parse(ANSWER), **context})


def _phase(**config):
    return PhasedNode(id="work", kind="phase", title="Work",
                      config={"workflow_contract": {"capability_class": "change"}, **config})


def test_a_role_phase_gets_its_tasks_and_a_phase_without_tasks_gets_all():
    role = phase_definition(_run(), _phase(tasks="backend"))["workflow_contract"][RUN_PHASE_CONTRACT_KEY]
    assert [item["id"] for item in role["task_list"]] == ["T1", "T4"]
    whole = phase_definition(_run(), _phase())["workflow_contract"][RUN_PHASE_CONTRACT_KEY]
    assert [item["id"] for item in whole["task_list"]] == ["T1", "T2", "T3", "T4"]  # ticket delivery as today
    writer = phase_definition(_run(), _phase(sets_task_list=True))["workflow_contract"][RUN_PHASE_CONTRACT_KEY]
    assert "task_list" not in writer  # it writes the list; the builders' proofs are not its work


@pytest.mark.asyncio
async def test_a_change_phase_with_sets_task_list_stores_the_list_from_its_answer():
    from app.services.workflow_runs.octryx.stop_answers import _keep_task_list

    run = SimpleNamespace(id="r1", work_item_id=None, context={})
    await _keep_task_list(None, run, _phase(), ANSWER)
    assert "task_list" not in run.context  # a plain building phase never sets the list
    await _keep_task_list(None, run, _phase(sets_task_list=True), ANSWER)
    assert [item["id"] for item in run.context["task_list"]] == ["T1", "T2", "T3", "T4"]
    assert {item["status"] for item in run.context["task_list"]} == {"open"}


@pytest.mark.asyncio
async def test_a_role_phase_moves_only_its_own_tasks():
    from app.services.workflow_runs.octryx.stop_answers import _keep_task_list

    tasks = [{**item, "status": "done"} for item in parse(ANSWER)]
    run = SimpleNamespace(id="r1", work_item_id=None, context={"task_list": tasks})
    change = {"patch": "diff --git a/tests/test_corpus.py b/tests/test_corpus.py\n+def test_corpus():\n"}
    await _keep_task_list(None, run, _phase(tasks="frontend"), "done", change=change)
    statuses = {item["id"]: item["status"] for item in run.context["task_list"]}
    # The frontend's T2/T3 have no proof in the change (open), its untagged T4 has (in progress until a passed pass);
    # T1 is the backend's and keeps its status.
    assert statuses == {"T1": "done", "T2": "open", "T3": "open", "T4": "in_progress"}


def _graph(between: dict | None = None) -> object:
    nodes = [{"id": "start", "type": "start"},
             *({"id": name, "type": "phase", "label": name, "config": {}} for name in ("backend", "frontend", "tests")),
             {"id": "pipeline", "type": "platform_action", "label": "CI", "config": {"action": "pipeline.run"}},
             {"id": "done", "type": "outcome", "config": {"outcome": "done"}}]
    chain = ["start", "backend", "frontend", "tests", "pipeline", "done"]
    if between:
        nodes.append(between)
        chain.insert(chain.index("tests"), between["id"])
    edges = [{"id": f"e{n}", "source_node_id": a, "target_node_id": b} for n, (a, b) in enumerate(zip(chain, chain[1:]))]
    edges.append({"id": "loop", "source_node_id": "pipeline", "target_node_id": "backend", "when": "failed",
                  "kind": "loop", "max_iterations": 3})
    return parse_phased_definition({"execution_kind": "phased", "nodes": nodes, "edges": edges})


def test_the_pipeline_follows_through_further_phases():
    graph = _graph()
    assert all(pipeline.follows(graph, node, TEST_ENV) for node in ("backend", "frontend", "tests"))
    assert not pipeline.follows(graph, "backend", {})


@pytest.mark.parametrize("between", [
    {"id": "check", "type": "review", "label": "Review", "config": {"phase": "frontend"}},
    {"id": "ask", "type": "user_confirmation", "label": "Ask", "config": {"subject": "readiness"}},
])
def test_a_review_or_confirmation_in_between_keeps_the_stop_s_own_checks(between):
    graph = _graph(between)
    assert not pipeline.follows(graph, "backend", TEST_ENV)
    assert not pipeline.follows(graph, "frontend", TEST_ENV)
    assert pipeline.follows(graph, "tests", TEST_ENV)


def _decided(findings, statuses=("verified", "verified"), **context):
    tasks = [{"id": f"T{n}", "text": "x", "proof": f"tests/a.py::test_{n}", "status": status}
             for n, status in enumerate(statuses, 1)]
    return SimpleNamespace(context={"review": {"verdict": "changes" if findings else "pass", "findings": findings},
                                    "task_list": tasks, **context})


def test_revise_on_high_accepts_at_once_without_a_high_finding():
    medium = [{"severity": "medium", "fix": "spacing"}, {"severity": "low", "fix": "naming"}]
    assert accept_reason(_decided(medium)) == ""  # the default still revises on a medium
    assert accept_reason(_decided(medium), revise_on="high") == (
        "no high finding (revise only on high); 2 medium or low findings are notes for the product owner, "
        "all 2 tasks verified")
    assert accept_reason(_decided([*medium, {"severity": "high", "fix": "T2: no cards"}]), revise_on="high") == ""
    assert accept_reason(_decided(medium, ("verified", "done")), revise_on="high") == ""


def test_a_skipped_pipeline_needs_no_verified_tasks():
    skipped = {"pipeline": {"state": "skipped"}}
    assert accept_reason(_decided([], ("open", "done"))) == ""
    assert accept_reason(_decided([], ("open", "done"), **skipped)) == (
        "review passed; 2 tasks not verified: the pipeline was skipped on the server")
    high = [{"severity": "high", "fix": "x"}]
    assert accept_reason(_decided(high, ("open",), **skipped), revise_on="high") == ""  # a high finding still asks
