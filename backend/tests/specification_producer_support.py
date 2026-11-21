"""Shared helpers for the test_specification_producer_* modules."""

import copy
import uuid

from app.models import ToolCall, User, UserProject, WorkflowRunDecision
from app.services.workflow_runs.phase_outputs import output_hash
from app.services.workflow_runs.records import record_event
from app.services.workflow_runs.specification.lineage import (
    canonicalize_output,
    record_output_provenance,
    take_output_provenance,
)
from app.time_utils import utc_now
from tests.specification_definition_support import BUDGET
from tests.workflow_artefact_review_support import prepared

KEY = "actual-evidence-key"


IDEA = {"schema_version": "idea_frame/v1", "summary": "Idea", "problem": "A concrete problem",
    "desired_outcome": "An inspectable specification", "scope": {"in_scope": ["Specification"], "out_of_scope": []},
    "constraints": [], "open_questions": [], "deferred_questions": []}


PLAN = {"schema_version": "research_plan/v1", "questions": [{"id": "RQ1", "text": "What does the source establish?"}],
        "source_kinds": ["knowledge"], "egress": "none"}


BRIEF = {"schema_version": "research_brief/v1", "summary": "Observation, not a causal proof",
    "claims": [{"id": "CL1", "text": "A test observation.", "evidence_keys": [KEY]}],
    "contradictions": [], "uncertainty": [{"claim_ids": ["CL1"], "text": "Cause remains unknown."}]}


SPEC = {"schema_version": "spec/v1", "summary": "Proposed specification",
    "stories": [{"id": "ST1", "as_a": "Reader", "i_want": "Inspect evidence", "so_that": "I can judge a claim"}],
    "criteria": [{"id": "AC1", "story_ids": ["ST1"], "given": "An admitted source", "when": "I view the claim",
                  "then": "I can inspect its source"}], "nfrs": [], "risks": [],
    "documentation_audience": {"semantics": "workspace_readers", "description": "Readers of this workspace"},
    "claims": BRIEF["claims"], "contradictions": [], "uncertainty": BRIEF["uncertainty"], "open_questions": []}


async def enter(db, run, node):
    run.current_node_id = node
    run.node_state = {"entry": int(run.node_state.get("entry", 0)) + 1, "entered_at": utc_now().isoformat()}
    record_event(db, run, "node_entered", node_id=node, detail={"entry": run.node_state["entry"]})
    await db.flush()


async def put(db, run, kind, record, *, confirm=False, proof=None):
    previous = run.context.get("outputs", {}).get(kind, {})
    envelope = {"kind": kind, "version": previous.get("version", 0) + 1, "hash": output_hash(record),
        "node_id": run.current_node_id, "entry": run.node_state["entry"], "at": utc_now().isoformat(), "record": record}
    run.context = {**run.context, "outputs": {**run.context.get("outputs", {}), kind: envelope}}
    record_event(db, run, "phase_output_recorded", node_id=run.current_node_id,
                 detail={"kind": kind, "hash": envelope["hash"], "version": envelope["version"]})
    await record_output_provenance(db, run, kind, proof=proof)
    if confirm:
        payload = {"shows": kind, "output": {**record, "version": envelope["version"], "hash": envelope["hash"]}}
        db.add(WorkflowRunDecision(run_id=run.id, node_id=run.current_node_id, kind="confirmation", subject="advance",
            action="confirmed", payload=payload, payload_hash=output_hash(payload), decided_by=run.requested_by))
    await db.flush()


async def producer(db, *, complete=True):
    run, session, source, revision, _ = await prepared(db)
    actor = User(id=str(uuid.uuid4()), username="spec-producer", email="producer@example.test",
                 password_hash="test-only-not-a-login", is_active=True, account_type="human")
    db.add_all([actor, UserProject(user_id=actor.id, project_id=run.project_id, role="viewer")])
    await db.flush()  # the user row exists before the run references it (PostgreSQL enforces the FK)
    run.requested_by = actor.id
    session.user_id = actor.id
    await db.flush()
    run.limits = {"budget": dict(BUDGET)}
    await enter(db, run, "idea")
    await put(db, run, "idea_frame", await canonicalize_output(db, run, "idea_frame", IDEA, principal=actor), confirm=True)
    await enter(db, run, "plan")
    await put(db, run, "research_plan", await canonicalize_output(db, run, "research_plan", PLAN, principal=actor), confirm=True)
    await enter(db, run, "research")
    key = revision.id.replace("-", "") + ":1"
    call = ToolCall(id=str(uuid.uuid4()), session_id=session.id, tool_name="knowledge_read",
        parameters={"evidence_key": key}, result={"state": "ok", "evidence_key": key}, status="success", request_id="turn-1")
    db.add(call)
    await db.flush()
    kwargs = {"principal": actor, "session_id": session.id, "request_id": "turn-1", "tool_history": [
        {"tool_name": "knowledge_read", "persisted_call_id": call.id, "result": {"state": "ok"}}]}
    brief = copy.deepcopy(BRIEF)
    brief["claims"][0]["evidence_keys"] = [key]
    if complete:
        canonical = await canonicalize_output(db, run, "research_brief", brief, **kwargs)
        proof = take_output_provenance(db, run, "research_brief", canonical, session_id=session.id, request_id="turn-1")
        await put(db, run, "research_brief", canonical, proof=proof)
        await enter(db, run, "draft")
        spec = copy.deepcopy(SPEC)
        spec["claims"][0]["evidence_keys"] = [key]
        await put(db, run, "spec", await canonicalize_output(db, run, "spec", spec, principal=actor))
    await db.flush()
    return run, actor, session, source, revision, call, kwargs, brief
