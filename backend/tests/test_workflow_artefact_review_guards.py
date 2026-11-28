"""An artefact review holds unproved inputs before the model, never records on input drift, claims an attempt once, never reuses an old verdict, and withholds the internal snapshot from a source-denied viewer."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.models.project.knowledge_evidence import KnowledgeSourceHead
from app.services.workflow_runs.phase_outputs import output_hash
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_artefact_review_support import CHANGES, PASS, prepared
from tests.workflow_run_review_support import ScriptedReviewer

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["body", "old_pass", "failed_call", "foreign_call", "missing_call", "old_call", "url", "handoff"])
async def test_unproved_input_is_held_before_model(db, drift):
    run, session, _, _, call = await prepared(db)
    context = copy.deepcopy(run.context)
    envelope = context["outputs"]["incident_hypothesis"]
    if drift == "body":
        envelope["record"]["cause"] = "Opposite same-name draft"
    elif drift == "old_pass":
        envelope["entry"] += 1
    elif drift == "failed_call":
        call.status = "error"
    elif drift == "foreign_call":
        from app.models import Session
        foreign = Session(user_id=run.requested_by, project_id=run.project_id)
        db.add(foreign)
        await db.flush()
        call.session_id = foreign.id
    elif drift == "old_call":
        from datetime import timedelta
        call.created_at -= timedelta(hours=1)
    elif drift == "missing_call":
        await db.delete(call)
    elif drift == "url":
        envelope["record"]["sources"] = ["https://display.example/no-authority"]
        envelope["hash"] = output_hash(envelope["record"])
    else:
        from app.models.runtime.flow_definition import FlowDefinitionVersion
        version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id)
        graph = copy.deepcopy(version.definition_json)
        graph["nodes"][2]["config"] = {"mode": "artefact", "kind": "incident_hypothesis",
            "source": "accepted_handoff", "rubric_version": 1}
        version.definition_json = graph
    run.context = context
    await db.commit()
    reviewer = ScriptedReviewer(PASS)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert not reviewer.tasks
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "needs_configuration")
    assert "review" not in run.context


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["redraft", "abort", "head", "acl", "owner", "review_pass"])
async def test_io_drift_never_records_or_advances(db, drift):
    run, _, source, revision, _ = await prepared(db)

    async def during():
        if drift == "redraft":
            context = copy.deepcopy(run.context)
            envelope = context["outputs"]["incident_hypothesis"]
            envelope["record"]["cause"] = "New draft"
            envelope["hash"] = output_hash(envelope["record"])
            envelope["version"] += 1
            run.context = context
        elif drift == "abort":
            run.status, run.waiting_kind = "stopped", None
        elif drift == "review_pass":
            run.node_state = {**run.node_state, "entry": run.node_state["entry"] + 1}
        elif drift == "head":
            head = await db.get(KnowledgeSourceHead, source.id)
            head.wanted_revision_id = None
        elif drift == "acl":
            from app.services.knowledge.access.source_acl import restrict_source
            await restrict_source(db, project_id=run.project_id, source_key=source.source_key, restriction="restricted")
        else:
            from app.models import User
            actor = await db.get(User, run.requested_by)
            actor.is_active = False
        await db.commit()

    reviewer = ScriptedReviewer(PASS, during=during)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 0
    await db.refresh(run)
    assert "review" not in run.context and run.current_node_id == "review"


@pytest.mark.asyncio
async def test_active_attempt_cannot_be_claimed_twice_and_invalid_answer_pauses(db):
    run, *_ = await prepared(db)
    second = ScriptedReviewer(PASS)

    async def during():
        assert await run_due_reviews(db, model_factory=second.factory) == 0

    reviewer = ScriptedReviewer({"verdict": "maybe"}, during=during)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert not second.tasks and len(reviewer.tasks) == 1
    await db.refresh(run)
    assert run.pause_reason == "review_no_decision" and "review" not in run.context


@pytest.mark.asyncio
async def test_old_verdict_cannot_serve_a_new_review_node_pass(db):
    run, *_ = await prepared(db)
    assert await run_due_reviews(db, model_factory=ScriptedReviewer(PASS).factory) == 1
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.records import record_event
    from app.services.workflow_runs.review.artefact_gate import gate_record

    record_event(db, run, "node_entered", node_id="review", detail={"entry": 999, "kind": "review"})
    await db.commit()
    gate = (await graph_for_run(db, run)).nodes["gate"]
    assert await gate_record(db, run, gate) is None


@pytest.mark.asyncio
async def test_run_events_withholds_internal_snapshot_from_source_denied_workspace_viewer(db, client):
    import json

    from app.services.auth.tokens import create_access_token
    from app.services.knowledge.access.authorization import authorize_workspace
    from app.services.knowledge.access.source_acl import restrict_source
    from app.services.knowledge.ledger.errors import EvidenceLedgerError
    from app.services.knowledge.ledger.reading import read_span_window
    from tests.knowledge_evidence_seed_support import fetch_user, seed_member

    run, _, source, _, call = await prepared(db)
    quoted = copy.deepcopy(CHANGES)
    quoted["findings"][0]["reason"] = "Observed: tests passed; source quote not for other readers"
    assert await run_due_reviews(db, model_factory=ScriptedReviewer(quoted).factory) == 1
    viewer_id = await seed_member(db, workspace_id=run.project_id, role="viewer")
    viewer = await fetch_user(db, viewer_id)
    await restrict_source(db, project_id=run.project_id, source_key=source.source_key, restriction="restricted")
    await db.commit()
    authorized = await authorize_workspace(db, current_user=viewer, workspace_id=run.project_id)
    with pytest.raises(EvidenceLedgerError):
        await read_span_window(db, authorized=authorized, evidence_key=call.parameters["evidence_key"], window=0)
    response = await client.get(f"/api/v1/workflow-runs/{run.id}/events", headers={
        "Authorization": f"Bearer {create_access_token(viewer.id)}"})
    assert response.status_code == 200, response.text
    events = response.json()["events"]
    projected = next(item["detail"] for item in events if item["kind"] == "artefact_review_snapshot")
    assert projected["content_withheld"] and projected["snapshot_hash"]
    assert projected["evidence_refs"][0]["call_id"] == call.id
    public = json.dumps(response.json())
    assert "Observed: tests passed" not in public and "Insufficient evidence; a transient" not in public
    assert "principal_keys" not in json.dumps(projected) and "snapshot" not in projected
    internal = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
        WorkflowRunEvent.kind == "artefact_review_snapshot"))).scalar_one()
    assert "Observed: tests passed" in internal.detail["snapshot"]["evidence"][0]["text"]
    assert "_snapshot" not in run.context["review"]
    run_response = await client.get(f"/api/v1/workflow-runs/{run.id}", headers={
        "Authorization": f"Bearer {create_access_token(viewer.id)}"})
    assert run_response.status_code == 200 and "Observed: tests passed" not in run_response.text
