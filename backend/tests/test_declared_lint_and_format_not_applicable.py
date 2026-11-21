"""A not-applicable check is no failure: a reviewer pass with a not-applicable test check passes the review gate, a gate with only not-applicable checks still fails."""

from __future__ import annotations

import copy

import pytest

from app.services.workflow_runs.records import new_chat_session, start_run
from tests.declared_lint_and_format_only_support import (  # noqa: F401
    _gate_definition,
    _kinds,
    _server_pipeline,
    _started,
)
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace
from tests.test_workflow_run_pause import _turn
from tests.workflow_run_review_support import PASS, ScriptedReviewer

# (c) not applicable is no failure ------------------------------------------------------------------------------------


def _reviewed_definition(gate_checks: list[dict]) -> dict:
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "work", "type": "phase", "label": "Implement", "config": copy.deepcopy(PHASE)},
                  {"id": "independent_review", "type": "review", "label": "Independent review"},
                  {"id": "review", "type": "gate", "config": {"phase": "work", "checks": gate_checks}},
                  {"id": "push", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "work"},
                  {"id": "2", "source_node_id": "work", "target_node_id": "independent_review"},
                  {"id": "3", "source_node_id": "independent_review", "target_node_id": "review"},
                  {"id": "4", "source_node_id": "review", "target_node_id": "push", "when": "passed"},
                  {"id": "5", "source_node_id": "review", "target_node_id": "work", "when": "failed",
                   "kind": "loop", "max_iterations": 2}],
    }


TEST_GATE = {"type": "test_command_passed", "params": {}, "blocking": True,
             "description": "The last test run after the last change passed"}


@pytest.mark.asyncio
async def test_a_reviewer_pass_with_a_not_applicable_test_check_passes_the_review_gate(db, tmp_path):
    from tests.workflow_run_review_support import changed_repo

    review = {"type": "review_passed", "params": {}, "blocking": True, "description": "The reviewer passed"}
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(changed_repo(tmp_path / "w"))}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _reviewed_definition(
        [review, TEST_GATE])), project_id=workspace_id, session=session)
    await db.commit()
    await _turn(db, session.id, ["knowledge_search"])

    from app.services.workflow_runs.review.runner import run_due_reviews

    assert await run_due_reviews(db, model_factory=ScriptedReviewer(PASS).factory) == 1
    await db.refresh(run)

    results = {item["type"]: item["outcome"] for item in run.gate_results["review"]["results"]}
    assert results == {"review_passed": "passed", "test_command_passed": "not_applicable"}
    assert (run.status, run.outcome) == ("completed", "done")
    assert "loop" not in str(dict(run.context or {}).get("loops") or {})  # no review loop consumed
    assert (await _kinds(db, run)).count(("node_entered", "work")) == 1  # never back to the fix


@pytest.mark.asyncio
async def test_a_gate_whose_checks_are_all_not_applicable_still_fails(db):
    _admin, session, run = await _started(db, _gate_definition([TEST_GATE]))

    await _turn(db, session.id, ["knowledge_search"])

    assert run.gate_results["green"]["state"] == "failed" and run.current_node_id == "implement"
