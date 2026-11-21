"""A test-first run's test contract must specify the new behaviour.

A Clarify agent can submit a contract with only existing tests, all ``regression``, none ``new``; accepting it, the
Clarify check would pass and the confirmation card would show a contract under which the run delivers nothing.

Real phase path: the registry's ``submit_test_contract`` tool (the handler a phase turn calls), the run's phase
checks through the turn-end checks guard, and the seeded A–E definitions for which runs are test-first.
"""

from __future__ import annotations

import copy
import json

import pytest

from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.contract_coverage import graph_requires_new_tests
from app.services.workflow_runs.graph import parse_phased_definition
from tests.contract_coverage_support import (  # noqa: F401
    NEW,
    REGRESSION,
    _clarify,
    _criterion,
    _server_pipeline,
    _submit,
)
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import phase_turn
from tests.test_workflow_run_hitl import contract_definition

DOR = ["truncate_words keeps the first n words joined by single spaces",
       "an ellipsis follows the last kept word when words were dropped",
       "max_words 0 returns an empty string"]


ALL_REGRESSION = [_criterion("AC1", "existing behaviour keeps working", [(test, "regression") for test in REGRESSION])]


VALID = [_criterion(f"AC{index}", text, [(NEW[index - 1], "new")]) for index, text in enumerate(DOR, start=1)] + [
    _criterion("AC4", "existing behaviour keeps working", [(test, "regression") for test in REGRESSION])]


async def _events(db, run) -> list:
    from sqlalchemy import select

    from app.models import WorkflowRunEvent

    return list((await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars())


@pytest.mark.asyncio
async def test_an_all_regression_contract_is_refused_and_the_clarify_check_fails(db, tmp_path):
    run, session, context = await _clarify(db, tmp_path)

    answer = await _submit(context, ALL_REGRESSION)

    assert answer["status"] == "refused" and answer["error"] == "invalid_output"
    assert "every test is 'regression'" in answer["message"] and "at least one 'new' test" in answer["message"]
    assert "outputs" not in run.context or "test_contract" not in run.context["outputs"]
    # The phase's own check sees the failed submit: not verified (the guard reminds once), never the card.
    resolution = await run_turn_resolution(db, session, user_message="Clarify.")
    outcome = await phase_turn(db, session.id, resolution, ["knowledge_search"])
    assert outcome is not None and outcome.get("action") == "continue"  # the one checks reminder
    assert run.current_node_id == "clarify"


@pytest.mark.asyncio
async def test_a_contract_missing_a_work_item_criterion_is_refused_with_the_criterion(db, tmp_path):
    _run, _session, context = await _clarify(db, tmp_path, dor=DOR)
    missing_ac2 = [criterion for criterion in VALID if criterion["id"] != "AC2"]

    answer = await _submit(context, missing_ac2)

    assert answer["status"] == "refused"
    assert "AC2: the Work item's confirmed Definition of Ready (triage run " in answer["message"]
    assert "lists \"an ellipsis follows" in answer["message"]
    assert "AC1" not in answer["message"] and "AC3" not in answer["message"]


@pytest.mark.asyncio
async def test_a_work_item_criterion_covered_only_by_regression_is_refused(db, tmp_path):
    _run, _session, context = await _clarify(db, tmp_path, dor=DOR)
    regression_ac3 = [*VALID[:2], _criterion("AC3", DOR[2], [(REGRESSION[0], "regression")]), VALID[3]]

    answer = await _submit(context, regression_ac3)

    assert answer["status"] == "refused" and "AC3:" in answer["message"]


@pytest.mark.asyncio
async def test_a_valid_contract_is_recorded_and_the_clarify_check_passes(db, tmp_path):
    run, session, context = await _clarify(db, tmp_path, dor=DOR)

    answer = await _submit(context, VALID)

    assert answer["status"] == "recorded", answer
    record = run.context["outputs"]["test_contract"]["record"]
    assert [criterion["id"] for criterion in record["criteria"]] == ["AC1", "AC2", "AC3", "AC4"]
    resolution = await run_turn_resolution(db, session, user_message="Clarify.")
    await phase_turn(db, session.id, resolution, ["knowledge_search", "submit_test_contract"])
    # The person's confirmation is still its own gate: the run waits at it.
    assert (run.current_node_id, run.waiting_kind) == ("contract", "awaiting_confirmation")


@pytest.mark.asyncio
async def test_an_explicitly_manual_only_criterion_counts_and_a_free_text_item_needs_only_one_new_test(db, tmp_path):
    _run, _session, context = await _clarify(db, tmp_path, dor=DOR)
    manual_ac3 = [*VALID[:2], {"id": "AC3", "text": DOR[2], "manual_only": True,
                               "manual_reason": "checked in the UI copy"}, VALID[3]]
    assert (await _submit(context, manual_ac3))["status"] == "recorded"

    _run2, _session2, no_dor = await _clarify(db, tmp_path)  # no structured criteria: rule 1 only, no text parsing
    one_new = [_criterion("AC1", "truncate_words", [(NEW[0], "new"), (REGRESSION[0], "regression")])]
    assert (await _submit(no_dor, one_new))["status"] == "recorded"


@pytest.mark.asyncio
async def test_a_run_without_a_red_gate_is_unaffected(db, tmp_path):
    _run, _session, context = await _clarify(db, tmp_path, definition=contract_definition())

    assert (await _submit(context, copy.deepcopy(ALL_REGRESSION)))["status"] == "recorded"


def test_of_the_seeded_workflows_only_feature_delivery_is_test_first():
    test_first = {seed["key"]: graph_requires_new_tests(parse_phased_definition(seed["definition"]))
                  for seed in seed_definitions()}

    assert test_first == {"bug-fix-reproduction": False, "jira-intake-triage": False, "feature-delivery-tdd": True,
                          "incident-analysis": False, "spec-writing": False, "team-delivery": False,
                          # One plain Claude Code session per epic: no tests_red gate.
                          "epic-delivery": False,
                          # The PR review bot reviews someone else's pull request; it never writes code or tests.
                          "pr-review-bot": False, "pr-review-explain": False,
                          "pr-fix": False}


def test_the_trace_names_the_runs_working_copy_and_base():
    from app.services.workflow_runs.phase_workspace import run_copy_trace_fields

    fields = run_copy_trace_fields({"run_working_copy": "/app/data/session-workspaces/s/run-copies/c",
                                    "run_base_sha": "3215a0be"})
    assert fields == {"run_working_copy": "/app/data/session-workspaces/s/run-copies/c", "run_base_sha": "3215a0be"}
    assert run_copy_trace_fields({"workspace_root": "/x"}) == {}
    assert json.dumps(fields)


@pytest.mark.asyncio
async def test_only_work_item_criteria_need_new_tests_and_the_source_is_named(db, tmp_path):
    run, _session, context = await _clarify(db, tmp_path, dor=DOR)
    # AC4 is the agent's own criterion: regression-only is fine.
    assert (await _submit(context, VALID))["status"] == "recorded"
    source = run.context["outputs"]["test_contract"]["record"]["criteria_source"]
    assert source["source"].startswith("the Work item's confirmed Definition of Ready (triage run ")
    assert source["work_item_criteria"] == 3 and "stays the person's check" in source["note"]

    missing = await _submit(context, [criterion for criterion in VALID if criterion["id"] != "AC1"])
    assert "AC1: the Work item's confirmed Definition of Ready (triage run " in missing["message"]


@pytest.mark.asyncio
async def test_without_a_structured_source_the_record_says_the_ticket_match_is_the_persons(db, tmp_path):
    run, _session, context = await _clarify(db, tmp_path)

    assert (await _submit(context, [_criterion("AC1", "truncate_words", [(NEW[0], "new")])]))["status"] == "recorded"

    source = run.context["outputs"]["test_contract"]["record"]["criteria_source"]
    assert source["source"] is None and source["work_item_criteria"] == 0
    assert "no structured acceptance criteria" in source["note"] and "stays the person's check" in source["note"]


@pytest.mark.asyncio
async def test_an_automatic_refusal_is_no_decision_and_keeps_the_recorded_contract(db, tmp_path):
    run, session, context = await _clarify(db, tmp_path)
    first = await _submit(context, [_criterion("AC1", "truncate_words", [(NEW[0], "new")])])
    assert first["status"] == "recorded"
    recorded = copy.deepcopy(run.context["outputs"]["test_contract"])
    before = (copy.deepcopy(run.loop_counters), copy.deepcopy(run.node_state), run.current_node_id, run.status)
    events = len(await _events(db, run))

    refused = await _submit(context, copy.deepcopy(ALL_REGRESSION))

    assert refused["status"] == "refused"
    assert run.context["outputs"]["test_contract"] == recorded  # version and hash unchanged: nothing rewritten
    assert (run.loop_counters, run.node_state, run.current_node_id, run.status) == before
    assert len(await _events(db, run)) == events  # no output, confirmation or rejection event


@pytest.mark.asyncio
async def test_the_structured_source_note_names_the_manual_exception(db, tmp_path):
    run, _session, context = await _clarify(db, tmp_path, dor=DOR)

    assert (await _submit(context, VALID))["status"] == "recorded"

    assert "new test or an explicit manual reason" in run.context["outputs"]["test_contract"]["record"][
        "criteria_source"]["note"]
