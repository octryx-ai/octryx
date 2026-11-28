"""Controls audit: a check that cannot decide with certainty lets the agent go on and leaves a
``check_uncertain`` note; it blocks only on a clear finding."""

from __future__ import annotations

import pytest

from app.services.workflow_checks.library import TurnEvidence, evaluate_checks
from app.services.workflow_runs.octryx.declared_commands import run_outcome
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

TEST = "tests/test_grind.py::test_default"


def test_a_piped_run_whose_summary_was_cut_is_unknown_not_red():
    assert run_outcome("pytest | tail -3", "pytest", succeeded=True, output="....") == "unknown"
    assert run_outcome("pytest | tail -3", "pytest", succeeded=True, output="3 passed in 0.2s") == "green"
    assert run_outcome("pytest | tail -3", "pytest", succeeded=True, output="1 failed, 2 passed in 0.3s") == "red"
    assert run_outcome("pytest | tail -3", "pytest", succeeded=False, output="....") == "red"
    assert run_outcome("pytest", "pytest", succeeded=True, output="") == "green"


def test_reproduces_passes_with_a_note_when_the_failure_message_was_cut():
    run = {"source": "device", "results": {TEST: {"outcome": "failed", "message": ""}}}
    evidence = TurnEvidence(tools=[], test_runs=[run], confirmed_tests=[TEST], symptom="starts at 0.0")
    [result] = evaluate_checks([{"type": "reproduces", "params": {}, "blocking": True}], evidence)
    assert result.outcome == "passed" and "symptom could not be compared" in result.uncertain
    assert result.as_dict()["uncertain"] == result.uncertain


@pytest.mark.asyncio
async def test_a_gate_none_of_whose_checks_could_be_judged_passes_with_a_note(db):
    from sqlalchemy import select

    from app.models import WorkflowRunEvent
    from app.services.workflow_runs.binding import run_turn_resolution
    from app.services.workflow_runs.records import new_chat_session, start_run
    from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace

    definition = phased_definition(max_iterations=2)
    gate = next(node for node in definition["nodes"] if node["id"] == "verify")
    gate["config"]["checks"] = [{"type": "ci_green", "blocking": True, "description": "CI is green"}]  # no CI yet
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=session)
    resolution = await run_turn_resolution(db, session, user_message="Collect it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    assert run.gate_results["verify"]["state"] == "passed" and run.status == "completed"
    [note] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "check_uncertain"))).scalars().all()
    assert note.detail["control"] == "gate:verify" and "no CI result" in note.detail["reason"]


@pytest.mark.asyncio
async def test_a_failing_scenario_writer_pauses_the_run_as_the_platforms_not_a_round_back(db, monkeypatch):
    from app.services.workflow_runs.pause_causes import cause_of

    assert cause_of("runtime_failed", {"code": "hands_on_scenarios_failed"}) == (
        "platform", "runtime_failed_codes.hands_on_scenarios_failed")
