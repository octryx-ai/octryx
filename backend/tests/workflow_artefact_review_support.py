"""Shared helpers for the test_workflow_artefact_review_* modules."""

from __future__ import annotations

import copy
import uuid

from app.models import Project, ToolCall
from app.models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from app.services.workflow_checks.library import ToolUse, TurnEvidence
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import RUN_RESOLUTION_KEY, record_phase_turn
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased

PASS = {"verdict": "pass", "summary": "Honest uncertainty, evidence and next step.", "findings": []}


CHANGES = {"verdict": "changes", "summary": "Uncertainty is missing.", "findings": [
    {"severity": "medium", "field_or_claim_id": "cause", "reason": "The evidence does not establish cause.",
     "requested_change": "Mark this as inference and identify an alternative."}]}


def definition():
    phase = copy.deepcopy(PHASE)
    phase.update(agent="assistant", output="incident_hypothesis")
    phase["tool_policy"]["allowlist"] = ["knowledge_read", "submit_incident_hypothesis"]
    phase["workflow_contract"]["checks"] = [{"type": "tool_called", "blocking": True,
        "description": "Recorded hypothesis", "params": {"tools": ["submit_incident_hypothesis"]}}]
    return {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"}, {"id": "hypothesis", "type": "phase", "config": phase},
        {"id": "review", "type": "review", "config": {"mode": "artefact", "kind": "incident_hypothesis",
            "source": "local_output", "producer": "hypothesis", "rubric_version": 1}},
        {"id": "gate", "type": "gate", "config": {"checks": [{"type": "artefact_review_passed",
            "description": "Bound hypothesis reviewed", "blocking": True, "params": {}}]}},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}}], "edges": [
        {"id": "1", "source": "start", "target": "hypothesis"},
        {"id": "2", "source": "hypothesis", "target": "review"},
        {"id": "3", "source": "review", "target": "gate"},
        {"id": "4", "source": "gate", "target": "done", "when": "passed"},
        {"id": "5", "source": "gate", "target": "hypothesis", "when": "failed", "kind": "loop",
         "max_iterations": 1}]}


async def prepared(db):
    project = Project(id=str(uuid.uuid4()), name="Artifact review acceptance", config={})
    db.add(project)
    await db.flush()
    actor = await admin_user(db)
    # A root-admin is not impersonating a different user; add ordinary explicit workspace membership too.
    from app.models import UserProject
    db.add(UserProject(user_id=actor.id, project_id=project.id, role="owner"))
    source = KnowledgeEvidenceSource(id=str(uuid.uuid4()), project_id=project.id,
                                     source_key="acceptance-hypothesis", display_title="Actual evidence")
    db.add(source)
    await db.flush()
    revision = KnowledgeSourceRevision(id=str(uuid.uuid4()), source_id=source.id, project_id=project.id,
        revision_ordinal=1, content_sha256="a" * 64, object_key="acceptance/a", object_bucket="acceptance", media_type="text/plain",
        byte_size=8, parser_name="plain", parser_version="1", parser_sandbox="none", state="projected")
    db.add(revision)
    await db.flush()
    key = revision.id.replace("-", "") + ":1"
    db.add_all([KnowledgeSourceHead(source_id=source.id, project_id=project.id,
        current_revision_id=revision.id, wanted_revision_id=revision.id), KnowledgeEvidenceSpan(
        project_id=project.id, revision_id=revision.id, evidence_key=key, span_ordinal=1,
        char_start=0, char_end=8, text="Observed: tests passed; the cause is unproved.", citation="Actual span")])
    key_flow = await publish_phased(db, definition())
    session = await new_chat_session(db, actor, project.id)
    run = await start_run(db, user=actor, project_id=project.id, session=session, workflow_key=key_flow)
    await db.commit()
    call = ToolCall(id=str(uuid.uuid4()), session_id=session.id, tool_name="knowledge_read",
                    parameters={"evidence_key": key}, result={"state": "ok"}, status="success")
    db.add(call)
    await db.flush()
    result = await submit_output(db, run, "submit_incident_hypothesis", {
        "summary": "Unproved cause", "cause": "Insufficient evidence; a transient failure is only an inference.",
        "impact": "No impact established", "next_step": "Inspect fresh logs", "code_fix_needed": False,
        "sources": [key]})
    assert result["state"] == "recorded", result
    marker = {"run_id": run.id, "node_id": "hypothesis", "entry": run.node_state["entry"]}
    await record_phase_turn(db, request_analysis={ROUTING_RESOLUTION_KEY: {RUN_RESOLUTION_KEY: marker}},
        session_id=session.id, state="passed", results=[], evidence=TurnEvidence(
            tools=[ToolUse("knowledge_read", True, call_id=call.id), ToolUse("submit_incident_hypothesis", True)]))
    await db.commit()
    return run, session, source, revision, call
