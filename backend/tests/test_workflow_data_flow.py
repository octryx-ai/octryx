"""The data-flow law of phased workflows and the phase output contract."""

from __future__ import annotations

import copy
import uuid

import pytest
from fastapi import HTTPException

from app.models import WorkflowRun
from app.models.runtime.flow_definition import FlowDefinition, FlowDefinitionVersion
from app.models.runtime.secure_work import WorkChangePlan, WorkItem
from app.services.secure_work.plans.run_plan import plan_rows
from app.services.workflow_runs.confirmation_payloads import confirmation_payload, reproduction_tests
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.octryx.actions import request_action
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.platform.work_plan import draft_change_plan
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_hitl import CRITERIA, contract_definition

pytestmark = pytest.mark.usefixtures("scripted_pool")


def _seed(key: str) -> dict:
    return copy.deepcopy(next(item for item in seed_definitions() if item["key"] == key)["definition"])


def _node(definition: dict, node_id: str) -> dict:
    return next(node for node in definition["nodes"] if node["id"] == node_id)


def _codes(definition: dict) -> list[str]:
    return [error["code"] for error in validate_phased_definition(definition)["errors"]]


def _without_draft(definition: dict) -> dict:
    definition["nodes"] = [node for node in definition["nodes"] if node["id"] != "draft_plan"]
    definition["edges"] = [edge for edge in definition["edges"] if edge["source_node_id"] != "draft_plan"]
    next(edge for edge in definition["edges"] if edge["id"] == "e-clarify")["target_node_id"] = "contract"
    return definition


def test_every_shipped_workflow_satisfies_the_law():
    for seed in seed_definitions():
        assert validate_phased_definition(seed["definition"])["errors"] == [], seed["key"]


def test_publish_refuses_every_consumer_without_a_producer_before_it():
    assert "consumer_without_producer" in _codes(_without_draft(_seed("feature-delivery-tdd")))
    no_tool = _seed("feature-delivery-tdd")
    _node(no_tool, "clarify")["config"]["tool_policy"]["allowlist"].remove("submit_test_contract")
    assert "phase_output_contract" in _codes(no_tool)
    unknown = _seed("feature-delivery-tdd")
    _node(unknown, "clarify")["config"]["output"] = "release_notes"
    assert "unknown_phase_output" in _codes(unknown)
    incident = _seed("incident-analysis")
    hypothesis = _node(incident, "hypothesis")["config"]
    hypothesis.pop("output")
    hypothesis["tool_policy"]["allowlist"].remove("submit_incident_hypothesis")
    messages = [error["message"] for error in validate_phased_definition(incident)["errors"]]
    assert {node for node in ("confirm_fix", "bug", "bugfix") if any(f"'{node}'" in text for text in messages)} == {
        "confirm_fix", "bug", "bugfix"}
    bug_fix = _seed("bug-fix-reproduction")
    _node(bug_fix, "reproduce")["config"].pop("output")
    _node(bug_fix, "reproduce")["config"]["tool_policy"]["allowlist"].remove("submit_reproduction")
    assert _codes(bug_fix).count("consumer_without_producer") == 2


@pytest.mark.asyncio
async def test_a_definition_with_a_gap_is_never_published(db):
    with pytest.raises(HTTPException) as refused:
        await publish_phased(db, _without_draft(_seed("feature-delivery-tdd")))
    assert refused.value.status_code == 422


async def _clarify_run(db, *, project_id: str | None = None):
    admin = await admin_user(db)
    item = WorkItem(source_type="jira", source_instance="t", source_key=f"DF-{uuid.uuid4().hex[:6]}",
                    title="Totals round down", project_id=project_id)
    db.add(item)
    await db.flush()
    workspace_id = await run_workspace(db, admin, item.id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, contract_definition()),
                          project_id=workspace_id,
                          work_item_id=item.id, session=await new_chat_session(db, admin, workspace_id))
    assert run.current_node_id == "clarify"
    return run, item


@pytest.mark.asyncio
async def test_a_submission_is_validated_versioned_and_only_accepted_in_its_phase(db):
    run, _item = await _clarify_run(db)
    outside = await submit_output(db, run, "submit_reproduction", {"tests": ["t::x"], "symptom": "boom"})
    assert (outside["state"], outside["reason"]) == ("refused", "outside_phase_output")
    malformed = await submit_output(db, run, "submit_test_contract", {"criteria": [
        {"id": "AC1", "text": "Rounds", "tests": ["t::x"]}, {"id": "AC1", "text": "Manual", "manual_only": True}]})
    assert malformed["reason"] == "invalid_output"
    assert {"AC1: name its tests and the command that runs them (or mark it manual_only with a reason)",
            "AC1: a manual-only criterion names why no test can prove it",
            "criteria: every criterion needs its own id"} <= set(malformed["problems"])
    assert "outputs" not in run.context
    first = await submit_output(db, run, "submit_test_contract", {"criteria": CRITERIA})
    second = await submit_output(db, run, "submit_test_contract", {"criteria": CRITERIA, "summary": "Totals"})
    assert (first["version"], second["version"]) == (1, 2) and first["hash"] != second["hash"]
    envelope = run.context["outputs"]["test_contract"]
    assert (envelope["node_id"], envelope["record"]["summary"]) == ("clarify", "Totals")


@pytest.mark.asyncio
async def test_the_draft_step_needs_the_contract_and_the_runs_workspace_and_is_idempotent_per_contract(db):
    from tests.agent_definition_revision_fixtures import make_project

    run, item = await _clarify_run(db)
    assert (await draft_change_plan(db, run)).reason == "no test contract was submitted in this run"
    await submit_output(db, run, "submit_test_contract", {"criteria": CRITERIA})
    drafted = await draft_change_plan(db, run)
    again = await draft_change_plan(db, run)
    assert drafted.ok and again.result["change_plan_id"] == drafted.result["change_plan_id"]
    first = await db.get(WorkChangePlan, drafted.result["change_plan_id"])
    assert first.validation_plan_json == [{"command": "pytest tests/test_billing.py",
                                          "source": "workflow_run_test_contract", "criteria": ["AC1"]}]
    await submit_output(db, run, "submit_test_contract", {"criteria": [*CRITERIA, {
        "id": "AC2", "text": "Receipt wording", "manual_only": True, "manual_reason": "A person reads it"}]})
    newer = await draft_change_plan(db, run)
    await db.refresh(first)
    assert (first.status, newer.result["version"]) == ("superseded", 2)
    assert run.context["change_plan"]["id"] == newer.result["change_plan_id"]

    other = await make_project(db)
    item.project_id = other.id
    await db.flush()
    assert (await draft_change_plan(db, run)).reason == "the Work item belongs to another Workspace than the run"


@pytest.mark.asyncio
async def test_an_agent_cannot_ask_for_the_draft_step(db):
    run, _item = await _clarify_run(db)
    answer = await request_action(db, run, action="work.draft_change_plan", params={})
    assert answer["reason"] == "unknown_action" and "work.draft_change_plan" not in answer["actions"]


@pytest.mark.asyncio
async def test_a_run_on_a_version_before_the_law_names_its_design_gap(db):
    admin = await admin_user(db)
    definition = _without_draft(_seed("feature-delivery-tdd"))
    flow = FlowDefinition(key=f"legacy-{uuid.uuid4().hex[:6]}", name="Legacy B", status="published", is_active=True,
                          created_by=admin.id)
    db.add(flow)
    await db.flush()
    version = FlowDefinitionVersion(flow_id=flow.id, version=1, status="published", definition_json=definition,
                                    validation_report={}, publish_metadata={}, runtime_settings={},
                                    policy_bindings={}, created_by=admin.id)
    item = WorkItem(source_type="jira", source_instance="t", source_key="BRD-8", title="Wrap text")
    db.add_all([version, item])
    await db.flush()
    run = WorkflowRun(workflow_kind="phased", workflow_key=flow.key, title="Legacy B", flow_definition_version_id=version.id,
                      work_item_id=item.id, status="waiting", waiting_kind="awaiting_confirmation",
                      current_node_id="contract", node_state={}, context={}, requested_by=admin.id, pull_request={},
                      loop_counters={}, limits={}, budget_usage={}, gate_results={})
    db.add(run)
    await db.flush()
    node = parse_phased_definition(definition).nodes["contract"]
    payload = await confirmation_payload(db, run, node)
    assert payload["design_gap"] is True and "no step that drafts the change plan" in payload["missing"]

    criteria, validation = plan_rows({"criteria": CRITERIA})
    db.add(WorkChangePlan(work_item_id=item.id, version=1, status="ready_for_review", title="Made in Work",
                          created_by=admin.id, acceptance_criteria_json=criteria, validation_plan_json=validation,
                          evidence_json={"plan_type": "coding_change"}))
    await db.flush()
    payload = await confirmation_payload(db, run, node)
    assert "missing" not in payload and payload["blockers"] == []


def test_a_confirmed_reproduction_binds_only_the_submitted_tests_the_server_saw_failing():
    failing = [{"id": "tests/test_a.py::test_x", "message": "assert 2 == 3"},
               {"id": "tests/test_b.py::test_flaky", "message": "timeout"}]
    assert reproduction_tests({"failing_tests": failing, "tests": ["tests/test_a.py::test_x"]}) == (
        ["tests/test_a.py::test_x"], "assert 2 == 3")
    assert reproduction_tests({"failing_tests": failing}) == (
        ["tests/test_a.py::test_x", "tests/test_b.py::test_flaky"], "assert 2 == 3")


def test_a_reproduction_named_from_the_repository_root_binds_the_test_the_app_folder_run_saw():
    failing = [{"id": "test/features/brews/grind_test.dart::OCX-89 starts at 15", "message": "Expected: '15.0'"},
               {"id": "test/features/brews/other_test.dart::unrelated", "message": "boom"}]
    named = ["coffee/flutter/claude/test/features/brews/grind_test.dart::OCX-89 starts at 15"]
    assert reproduction_tests({"failing_tests": failing, "tests": named}) == (
        ["test/features/brews/grind_test.dart::OCX-89 starts at 15"], "Expected: '15.0'")
    assert reproduction_tests({"failing_tests": failing, "tests": ["features/brews/rest/grind_test.dart::x"]})[0] == []
