"""Closed records and real current-principal ledger boundaries."""

import copy
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import User, UserProject, WorkflowRunDecision, WorkflowRunEvent
from app.models.project.knowledge_evidence import KnowledgeSourceHead
from app.models.project.knowledge_source_acl import KnowledgeSourceAcl, KnowledgeSourceAclPrincipal
from app.services.knowledge.access.acl_keys import principal_key_for_email
from app.services.workflow_runs.phase_outputs import output_hash
from app.services.workflow_runs.specification.lineage import (
    SpecificationUnavailable,
    canonicalize_output,
    resolve_spec_snapshot,
    take_output_provenance,
)
from app.time_utils import utc_now
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.specification_definition_support import BUDGET
from tests.specification_producer_support import SPEC, enter, producer, put

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def _windowed(db):
    from app.models.project.knowledge_evidence import KnowledgeEvidenceSpan

    run, actor, session, source, revision, call, kwargs, brief = await producer(db, complete=False)
    own = call.parameters["evidence_key"]
    neighbour = revision.id.replace("-", "") + ":2"
    db.add(KnowledgeEvidenceSpan(project_id=run.project_id, revision_id=revision.id, evidence_key=neighbour,
        span_ordinal=2, char_start=8, char_end=40, text="How to use: the neighbour states the example.",
        citation="Neighbour span"))
    call.result = {"state": "ok", "evidence_key": own, "passage_keys": [own, neighbour]}
    await db.flush()
    return run, call, kwargs, brief, own, neighbour


@pytest.mark.asyncio
async def test_actual_reads_current_pass_exact_refs_and_frozen_snapshot(db):
    run, actor, _, _, revision, call, _, _ = await producer(db)
    snapshot = await resolve_spec_snapshot(db, run, principal=actor, purpose="review")
    original = copy.deepcopy(snapshot)
    assert snapshot["evidence"][0]["call_id"] == call.id
    assert snapshot["evidence"][0]["content_sha256"] == revision.content_sha256
    assert snapshot["evidence"][0]["text_hash"] != "sha256:" + revision.content_sha256
    assert snapshot["binding"]["idea_frame_ref"]["decision_id"]
    assert snapshot["upstream"]["research_brief"]["hash"] == snapshot["binding"]["research_brief_ref"]["hash"]
    assert await resolve_spec_snapshot(db, run, principal=actor, purpose="confirm") == original
    snapshot["evidence"][0]["text"] = "changed copy"
    assert (await resolve_spec_snapshot(db, run, principal=actor))["evidence"] == original["evidence"]


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["failed", "foreign_session", "foreign_request", "old", "unknown", "no_history", "search_only", "failed_state", "malformed_result", "old_pass"])
async def test_unproved_calls_never_mutate_output_or_loop(db, drift):
    run, _, _, _, _, call, kwargs, brief = await producer(db, complete=False)
    before = copy.deepcopy((run.context, run.loop_counters, run.node_state))
    if drift == "failed":
        call.status = "error"
    elif drift == "foreign_session":
        call.session_id = str(uuid.uuid4())
    elif drift == "foreign_request":
        call.request_id = "other-turn"
    elif drift == "old":
        call.created_at -= timedelta(days=1)
    elif drift == "unknown":
        kwargs["tool_history"][0]["persisted_call_id"] = str(uuid.uuid4())
    elif drift == "no_history":
        kwargs["tool_history"] = []
    elif drift == "search_only":
        kwargs["tool_history"][0]["tool_name"] = "knowledge_search"
    elif drift == "failed_state":
        call.result = {"state": "not_found"}
    elif drift == "malformed_result":
        call.result = ["not a read"]
    elif drift == "old_pass":
        await enter(db, run, "research")
    await db.flush()
    before = copy.deepcopy((run.context, run.loop_counters, run.node_state))
    events = await db.scalar(select(func.count()).select_from(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))
    with pytest.raises(SpecificationUnavailable):
        await canonicalize_output(db, run, "research_brief", brief, **kwargs)
    assert (run.context, run.loop_counters, run.node_state) == before
    assert await db.scalar(select(func.count()).select_from(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id)) == events
    assert not db.info.get("specification_validated_reads", {}).get(run.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["head", "acl", "membership", "changed", "budget", "brief_hash", "proof", "call"])
async def test_review_pass_never_authorizes_stale_actual_confirmer(db, drift):
    run, actor, _, source, revision, call, _, _ = await producer(db)
    run.context = {**run.context, "review": {"verdict": "pass", "binding": {"hash": run.context["outputs"]["spec"]["hash"]}}}
    await resolve_spec_snapshot(db, run, principal=actor, purpose="preview")
    if drift == "head":
        head = await db.get(KnowledgeSourceHead, source.id)
        head.wanted_revision_id = None
    elif drift == "acl":
        db.add(KnowledgeSourceAcl(project_id=run.project_id, source_key=source.source_key, restriction="restricted"))
    elif drift == "membership":
        member = (await db.execute(select(UserProject).where(UserProject.user_id == actor.id,
                                                             UserProject.project_id == run.project_id))).scalar_one()
        await db.delete(member)
    elif drift == "changed":
        db.add(WorkflowRunDecision(run_id=run.id, kind="confirmation", subject="idea_frame", action="changed",
            decided_by=actor.id, payload={}, payload_hash=output_hash({})))
    elif drift == "budget":
        run.limits = {"budget": {**BUDGET, "tool_calls": 80}}
    elif drift == "brief_hash":
        run.context = copy.deepcopy(run.context)
        run.context["outputs"]["research_brief"]["record"]["summary"] = "Unreviewed claim"
    elif drift == "proof":
        for event in (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
            WorkflowRunEvent.kind == "specification_read_provenance"))).scalars():
            await db.delete(event)
    elif drift == "call":
        call.request_id = "different-request"
    await db.flush()
    before = copy.deepcopy((run.context, run.node_state, run.loop_counters))
    decisions = await db.scalar(select(func.count()).select_from(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id))
    with pytest.raises(SpecificationUnavailable) as raised:
        await resolve_spec_snapshot(db, run, principal=actor, purpose="confirm")
    assert source.id not in str(raised.value) and revision.id not in str(raised.value) and "Observed:" not in str(raised.value)
    assert (run.context, run.node_state, run.loop_counters) == before
    assert await db.scalar(select(func.count()).select_from(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id)) == decisions


@pytest.mark.asyncio
async def test_other_actual_viewer_is_not_granted_producer_source_rights(db):
    run, actor, _, source, _, _, kwargs, brief = await producer(db, complete=False)
    other = User(id=str(uuid.uuid4()), username="spec-viewer", email="viewer@example.test", password_hash="not-a-login",
                 is_active=True, account_type="human")
    db.add_all([other, UserProject(user_id=other.id, project_id=run.project_id, role="viewer"),
        KnowledgeSourceAcl(project_id=run.project_id, source_key=source.source_key, restriction="restricted"),
        KnowledgeSourceAclPrincipal(project_id=run.project_id, source_key=source.source_key,
                                    principal_key=principal_key_for_email(actor.email))])
    await db.flush()
    canonical = await canonicalize_output(db, run, "research_brief", brief, **kwargs)
    proof = take_output_provenance(db, run, "research_brief", canonical,
                                  session_id=kwargs["session_id"], request_id=kwargs["request_id"])
    await put(db, run, "research_brief", canonical, proof=proof)
    await resolve_spec_snapshot(db, run, principal=actor, kind="research_brief")
    with pytest.raises(SpecificationUnavailable, match="source_withheld_or_unavailable"):
        await resolve_spec_snapshot(db, run, principal=other, purpose="preview", kind="research_brief")


@pytest.mark.asyncio
async def test_missing_provenance_refuses_before_store(db):
    run, actor, session, _, _, _, kwargs, brief = await producer(db, complete=False)
    canonical = await canonicalize_output(db, run, "research_brief", brief, **kwargs)
    with pytest.raises(SpecificationUnavailable):
        take_output_provenance(db, run, "research_brief", canonical, session_id=session.id, request_id="wrong")
    assert "research_brief" not in run.context["outputs"]
    with pytest.raises(SpecificationUnavailable):
        take_output_provenance(db, run, "research_brief", canonical, session_id=session.id, request_id="turn-1")


@pytest.mark.asyncio
async def test_no_silent_source_rebind_or_evidence_truncation(db):
    run, actor, _, _, _, _, _, _ = await producer(db)
    record = copy.deepcopy(SPEC)
    record["claims"][0]["evidence_keys"] = ["another-valid-looking-key"]
    with pytest.raises(SpecificationUnavailable) as raised:
        await canonicalize_output(db, run, "spec", record, principal=actor)
    assert raised.value.code == "invalid_output"
    original = copy.deepcopy(run.context)
    from app.models.project.knowledge_evidence import KnowledgeEvidenceSpan
    span = (await db.execute(select(KnowledgeEvidenceSpan).where(
        KnowledgeEvidenceSpan.project_id == run.project_id))).scalar_one()
    span.text = "x" * 8001
    await db.flush()
    with pytest.raises(SpecificationUnavailable, match="source_content_unavailable"):
        await resolve_spec_snapshot(db, run, principal=actor)
    assert run.context == original


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["recorded_raise", "lowered", "decision_differs", "decision_before_plan"])
async def test_a_supported_budget_raise_after_the_plan_keeps_the_lineage_and_nothing_else_does(db, case):
    run, actor, *_ = await producer(db)
    raised = {**BUDGET, "active_seconds": BUDGET["active_seconds"] * 3}
    lowered = {**BUDGET, "active_seconds": BUDGET["active_seconds"] / 2}
    run.limits = {"budget": lowered if case == "lowered" else raised}
    decision = WorkflowRunDecision(run_id=run.id, node_id=run.current_node_id, kind="pause", subject="budget_limit",
        action="continue", decided_by=actor.id,
        payload={"keys": ["active_seconds"], "k": 2, "budget": dict(BUDGET) if case == "decision_differs" else run.limits["budget"]},
        payload_hash=output_hash({}))
    if case == "decision_before_plan":
        decision.created_at = utc_now() - timedelta(days=1)
    db.add(decision)
    await db.flush()
    if case == "recorded_raise":
        resolved = await resolve_spec_snapshot(db, run, principal=actor, purpose="review")
        assert resolved["envelope"]["hash"] == run.context["outputs"]["spec"]["hash"]
        return
    with pytest.raises(SpecificationUnavailable) as raised_error:
        await resolve_spec_snapshot(db, run, principal=actor, purpose="review")
    assert "research_budget_changed" in str(raised_error.value)


@pytest.mark.asyncio
async def test_a_neighbour_passage_the_read_showed_is_cited_and_frozen_by_its_own_key(db):
    run, call, kwargs, brief, own, neighbour = await _windowed(db)
    brief["claims"][0]["evidence_keys"] = [neighbour]
    canonical = await canonicalize_output(db, run, "research_brief", brief, **kwargs)
    [row] = canonical["evidence"]
    assert (row["evidence_key"], row["call_id"]) == (neighbour, call.id)
    assert row["text"] == "How to use: the neighbour states the example."


@pytest.mark.asyncio
@pytest.mark.parametrize("shown", ["unshown", "other_revision"])
async def test_a_key_no_read_showed_or_a_foreign_window_key_is_refused(db, shown):
    run, call, kwargs, brief, own, neighbour = await _windowed(db)
    if shown == "unshown":
        call.result = {"state": "ok", "evidence_key": own, "passage_keys": [own]}
        brief["claims"][0]["evidence_keys"] = [neighbour]
    else:
        call.result = {"state": "ok", "evidence_key": own, "passage_keys": [own, "f" * 32 + ":2"]}
    await db.flush()
    with pytest.raises(SpecificationUnavailable):
        await canonicalize_output(db, run, "research_brief", brief, **kwargs)
