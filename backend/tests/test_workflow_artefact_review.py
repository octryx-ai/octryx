"""S2c-1: actual server-resolved hypothesis inputs, independent worker and distinct gate."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.review.artefact_contract import parse_verdict, verdict_rejection
from app.services.workflow_runs.review.artefact_gate import evaluate
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_artefact_review_support import CHANGES, PASS, definition, prepared
from tests.workflow_run_review_support import ScriptedReviewer

pytestmark = pytest.mark.usefixtures("scripted_pool")


def test_closed_config_and_distinct_strict_verdict():
    assert validate_phased_definition(definition())["valid"]
    for key, value in [("kind", "spec"), ("mode", "unknown"), ("source", "latest"), ("rubric_version", True),
                       ("producer", "absent"), ("extra", "ignored")]:
        graph = definition()
        graph["nodes"][2]["config"][key] = value
        assert not validate_phased_definition(graph)["valid"], key
    assert parse_verdict(PASS).passed
    assert parse_verdict(CHANGES).findings[0].field_or_claim_id == "cause"
    assert parse_verdict({**PASS, "findings": CHANGES["findings"]}) is None
    assert parse_verdict({**PASS, "tree": "invented"}) is None
    assert evaluate({**PASS, "has_change": True, "tree": "dummy"})[0] == "failed"


def test_a_refused_answer_names_its_rule_without_its_text():
    finding = dict(CHANGES["findings"][0])
    assert verdict_rejection(PASS) == "" and verdict_rejection(CHANGES) == ""
    assert verdict_rejection(None) == "no_json_object"
    assert verdict_rejection({**PASS, "tree": "invented"}) == "top_level_keys"
    assert verdict_rejection({**PASS, "findings": CHANGES["findings"]}) == "pass_with_blocking_finding"
    assert verdict_rejection({**CHANGES, "findings": []}) == "changes_without_finding"
    assert verdict_rejection({**CHANGES, "findings": [{**finding, "reason": "x" * 1001}]}) == "finding_too_long"
    assert verdict_rejection({**CHANGES, "findings": [{**finding, "extra": "y"}]}) == "finding_keys"
    for refused in ({**CHANGES, "findings": [{**finding, "reason": "x" * 1001}]}, {**PASS, "tree": "invented"}):
        assert parse_verdict(refused) is None


def test_the_reviewer_has_room_for_thinking_and_the_verdict():
    from app.services.workflow_runs.review.model import MAX_ANSWER_TOKENS

    assert MAX_ANSWER_TOKENS >= 8000


@pytest.mark.asyncio
async def test_no_git_worker_reviews_exact_hash_and_distinct_gate(db):
    run, _, _, _, _ = await prepared(db)
    reviewer = ScriptedReviewer(PASS)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    await db.refresh(run)
    assert (run.status, run.outcome) == ("completed", "done")
    assert "tree" not in run.context["review"] and "has_change" not in run.context["review"]
    assert run.context["review"]["binding"]["hash"] == run.context["outputs"]["incident_hypothesis"]["hash"]
    assert run.context["review"]["reviewer_revision_id"]
    assert "Observed: tests passed" in reviewer.tasks[0][1]
    assert "No human acceptance" in reviewer.tasks[0][0]
    snapshots = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
        WorkflowRunEvent.kind == "artefact_review_snapshot"))).scalars().all()
    assert len(snapshots) == 1 and snapshots[0].detail["snapshot_hash"] == run.context["review"]["snapshot_hash"]


@pytest.mark.asyncio
async def test_changes_routes_field_findings_back_without_git(db):
    run, *_ = await prepared(db)
    assert await run_due_reviews(db, model_factory=ScriptedReviewer(CHANGES).factory) == 1
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("running", "hypothesis")
    assert run.gate_results["gate"]["state"] == "failed"
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.phase_contract import phase_definition

    phase = (await graph_for_run(db, run)).nodes["hypothesis"]
    facts = phase_definition(run, phase)["workflow_contract"]["workflow_run_phase"]
    assert facts["review_findings"] == ["cause [medium] The evidence does not establish cause.: "
                                         "Mark this as inference and identify an alternative."]
