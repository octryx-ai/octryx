"""Native spec review; producer authority is a test double, not live source proof."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_checks.library import ToolUse, TurnEvidence
from app.services.workflow_runs import phase_outputs
from app.services.workflow_runs.graph import graph_for_run
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.phase_outputs import OutputSpec, output_hash
from app.services.workflow_runs.review import artefact_evidence, spec_evidence
from app.services.workflow_runs.review.artefact_contract import answer_contract
from app.services.workflow_runs.review.artefact_gate import gate_record
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.workflow_artefact_review_support import CHANGES, PASS, definition, prepared
from tests.workflow_run_review_support import ScriptedReviewer


class SpecificationUnavailableError(Exception):
    code, reason = "needs_configuration", "source_or_lineage_unavailable"


@pytest.fixture
def spec_registry(monkeypatch):
    from app.services.run_capability import definition_contract
    original = definition_contract.tool_required_capability
    monkeypatch.setattr(definition_contract, "tool_required_capability",
                        lambda name: "read_only" if name == "submit_spec" else original(name))
    # Root owns central registration; no producer implementation is claimed by this fixture.
    monkeypatch.setitem(phase_outputs.OUTPUT_SPECS, "spec", OutputSpec("spec", "submit_spec", "Spec", lambda r: (r, [])))


def spec_definition():
    graph = definition()
    phase = graph["nodes"][1]["config"]
    phase["output"] = "spec"
    phase["tool_policy"]["allowlist"] = ["submit_spec"]
    phase["workflow_contract"]["checks"][0]["params"]["tools"] = ["submit_spec"]
    graph["nodes"][2]["config"]["kind"] = "spec"
    return graph


async def prepared_spec(db, monkeypatch):
    run, session, source, revision, call = await prepared(db)
    from app.models.runtime.flow_definition import FlowDefinitionVersion

    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id)
    version.definition_json = spec_definition()
    old = run.context["outputs"]["incident_hypothesis"]
    text = "Observed: tests passed; the cause is unproved."
    frozen = {"evidence_key": call.parameters["evidence_key"], "call_id": call.id, "source_id": source.id,
        "revision_id": revision.id, "content_sha256": revision.content_sha256, "text": text,
        "text_hash": output_hash({"text": text}), "cite_as": "Actual source", "retrieved_at": old["at"],
        "source_acl": {"workspace_id": run.project_id, "principal_user_id": run.requested_by,
                       "acl_hash": output_hash({"restriction": None, "principals": []})}}
    upstream = {
        "idea_frame": {"kind": "idea_frame", "node_id": "idea", "entry": 1, "version": 1,
                       "record": {"problem": "Human-confirmed inspectable evidence intent"}},
        "research_brief": {"kind": "research_brief", "node_id": "research", "entry": 2, "version": 1,
                           "record": {"summary": "Research observed tests", "evidence": [frozen]}}}
    for saved in upstream.values():
        saved["hash"] = output_hash(saved["record"])
    ref = {"parent_run_id": run.id, "node_id": "idea", "entry": 1, "version": 1,
           "kind": "idea_frame", "hash": upstream["idea_frame"]["hash"],
           "decision_id": "confirmed-idea", "decision_hash": "confirmed-idea-card"}
    record = {"schema_version": "spec/v1", "summary": "Proposed specification, engineering not started",
        "stories": [{"id": "ST1", "as_a": "reader", "i_want": "inspectable evidence", "so_that": "I can decide"}],
        "criteria": [{"id": "AC1", "story_ids": ["ST1"], "given": "a current source", "when": "read",
                      "then": "its exact source can be inspected"}],
        "nfrs": [], "risks": [], "documentation_audience": {"semantics": "workspace_readers", "description": "Readers"},
        "claims": [{"id": "CL1", "text": "Tests were observed passing", "evidence_keys": [frozen["evidence_key"]]}],
        "contradictions": [], "uncertainty": [], "open_questions": [], "idea_frame_ref": ref,
        "research_brief_ref": {"parent_run_id": run.id, **{key: upstream["research_brief"][key]
                                for key in ("kind", "node_id", "entry", "version", "hash")}}, "evidence": [frozen]}
    envelope = {**old, "kind": "spec", "record": record, "hash": output_hash(record)}
    run.context = {**run.context, "outputs": {"spec": envelope}}
    review_state = copy.deepcopy(run.node_state)
    run.node_state = {**run.node_state, "entry": envelope["entry"]}
    await artefact_evidence.record_provenance(db, run, node_id="hypothesis", session_id=session.id,
        state="passed", evidence=TurnEvidence(tools=[ToolUse("submit_spec", True)]))
    run.node_state = review_state
    authority = SimpleNamespace(calls=[], failure=False, binding_mutation=None, transform=None)

    async def resolve_spec_snapshot(_db, actual_run, *, principal, purpose):
        authority.calls.append((principal.id, purpose))
        if authority.failure:
            raise SpecificationUnavailableError()
        saved = copy.deepcopy(actual_run.context["outputs"]["spec"])
        binding = {key: saved[key] for key in ("kind", "version", "hash", "node_id", "entry")}
        binding.update(parent_run_id=actual_run.id, workspace_id=actual_run.project_id, principal_user_id=principal.id,
                       idea_frame_ref=saved["record"]["idea_frame_ref"],
                       research_brief_ref=saved["record"]["research_brief_ref"])
        binding.update(authority.binding_mutation or {})
        result = {"envelope": saved, "evidence": copy.deepcopy(saved["record"]["evidence"]), "binding": binding,
                  "upstream": copy.deepcopy(upstream)}
        if authority.transform:
            authority.transform(result)
        return result

    module = SimpleNamespace(SpecificationUnavailable=SpecificationUnavailableError, resolve_spec_snapshot=resolve_spec_snapshot)
    monkeypatch.setattr(spec_evidence, "import_module", lambda name: module)
    await db.commit()
    return run, authority


def test_spec_contract_is_closed_local_kind_with_its_own_rubric(spec_registry):
    graph = spec_definition()
    assert validate_phased_definition(graph)["valid"], validate_phased_definition(graph)
    for key, value in [("source", "accepted_handoff"), ("source", "latest"), ("kind", "research_brief"),
                       ("producer", "missing"), ("rubric_version", True), ("extra", "ignored")]:
        bad = copy.deepcopy(graph)
        bad["nodes"][2]["config"][key] = value
        assert not validate_phased_definition(bad)["valid"]
    assert "confirmed idea" in answer_contract("spec")
    assert "incident hypothesis" in answer_contract("incident_hypothesis")


@pytest.mark.asyncio
async def test_spec_native_worker_and_distinct_gate_freeze_exact_snapshot_without_git(db, monkeypatch, spec_registry):
    run, authority = await prepared_spec(db, monkeypatch)
    reviewer = ScriptedReviewer(PASS)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    await db.refresh(run)
    assert (run.status, run.outcome) == ("completed", "done")
    review = run.context["review"]
    assert review["binding"]["kind"] == "spec" and review["binding"]["hash"] == run.context["outputs"]["spec"]["hash"]
    assert review["reviewer_revision_id"] and "tree" not in review and "has_change" not in review and "_snapshot" not in review
    assert all(call == (run.requested_by, "review") for call in authority.calls) and len(authority.calls) >= 3
    system, task = reviewer.tasks[0]
    assert "confirmed idea" in system and "No human acceptance" in system and "Given/When/Then" in system
    assert "research_brief_ref" in task and "Observed: tests passed" in task and "retrieved_at" in task
    assert "Human-confirmed inspectable evidence intent" in task and "Research observed tests" in task
    event = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
        WorkflowRunEvent.kind == "artefact_review_snapshot"))).scalar_one()
    assert output_hash(event.detail["snapshot"]) == review["snapshot_hash"]
    assert event.detail["snapshot"]["evidence"] == run.context["outputs"]["spec"]["record"]["evidence"]
    from app.services.workflow_runs.review.artefact_projection import event_detail
    assert "Observed: tests passed" not in str(event_detail(event.kind, event.detail))


@pytest.mark.asyncio
async def test_spec_changes_still_fail_gate_and_loop_to_producer(db, monkeypatch, spec_registry):
    run, _ = await prepared_spec(db, monkeypatch)
    reviewer = ScriptedReviewer({**CHANGES, "findings": [{**CHANGES["findings"][0], "field_or_claim_id": "CL1"}]})
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert run.current_node_id == "hypothesis" and run.status == "running"
    assert run.gate_results["gate"]["state"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["draft", "old_pass", "upstream", "authority", "principal_binding", "resolver_missing", "failed_producer"])
async def test_unproved_spec_is_held_before_model(db, monkeypatch, spec_registry, drift):
    run, authority = await prepared_spec(db, monkeypatch)
    context = copy.deepcopy(run.context)
    saved = context["outputs"]["spec"]
    if drift == "draft":
        saved["record"]["summary"] = "Same-name unrecorded draft"
    elif drift == "old_pass":
        saved["entry"] += 1
    elif drift == "upstream":
        saved["record"]["idea_frame_ref"]["decision_hash"] = "new unconfirmed card"
        saved["hash"] = output_hash(saved["record"])
    elif drift == "authority":
        authority.failure = True
    elif drift == "failed_producer":
        event = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
            WorkflowRunEvent.kind == "artefact_phase_provenance").order_by(
            WorkflowRunEvent.created_at.desc(), WorkflowRunEvent.id.desc()).limit(1))).scalar_one()
        await db.delete(event)
    elif drift == "principal_binding":
        authority.binding_mutation = {"principal_user_id": "different-principal"}
    else:
        def missing(name):
            raise ModuleNotFoundError(name=name)
        monkeypatch.setattr(spec_evidence, "import_module", missing)
    run.context = context
    await db.commit()
    reviewer = ScriptedReviewer(PASS)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert not reviewer.tasks and run.status == "paused" and run.pause_reason == "needs_configuration"
    assert "review" not in run.context


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["redraft", "source_authority", "producer_pass", "review_pass"])
async def test_final_spec_recheck_discards_stale_verdict(db, monkeypatch, spec_registry, drift):
    run, authority = await prepared_spec(db, monkeypatch)

    async def during():
        if drift == "source_authority":
            authority.failure = True  # Producer tests actual ACL/head; this proves mandatory final delegation.
        elif drift == "review_pass":
            run.node_state = {**run.node_state, "entry": run.node_state["entry"] + 1}
        else:
            context = copy.deepcopy(run.context)
            saved = context["outputs"]["spec"]
            if drift == "producer_pass":
                saved["entry"] += 1
            else:
                saved["version"] += 1
                saved["record"]["summary"] = "New proposed spec"
                saved["hash"] = output_hash(saved["record"])
            run.context = context
        await db.commit()

    assert await run_due_reviews(db, model_factory=ScriptedReviewer(PASS, during=during).factory) == 0
    await db.refresh(run)
    assert "review" not in run.context and run.current_node_id == "review"


@pytest.mark.asyncio
async def test_spec_gate_rechecks_authority_and_old_pass_instead_of_reusing_verdict(db, monkeypatch, spec_registry):
    run, authority = await prepared_spec(db, monkeypatch)
    assert await run_due_reviews(db, model_factory=ScriptedReviewer(PASS).factory) == 1
    gate = (await graph_for_run(db, run)).nodes["gate"]
    assert await gate_record(db, run, gate)
    authority.failure = True
    assert await gate_record(db, run, gate) is None
    authority.failure = False
    from app.services.workflow_runs.records import record_event
    record_event(db, run, "node_entered", node_id="review", detail={"entry": 999, "kind": "review"})
    await db.commit()
    assert await gate_record(db, run, gate) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["upstream_body", "upstream_missing", "evidence_text", "evidence_missing"])
async def test_resolver_snapshot_must_match_immutable_envelope_and_upstream_refs(db, monkeypatch, spec_registry, drift):
    run, authority = await prepared_spec(db, monkeypatch)

    def change(result):
        if drift == "upstream_body":
            result["upstream"]["idea_frame"]["record"]["problem"] = "Unconfirmed intent"
        elif drift == "upstream_missing":
            del result["upstream"]["research_brief"]
        elif drift == "evidence_text":
            result["evidence"][0]["text"] = "Unrelated copied URL is not source proof"
        else:
            result["evidence"] = []
    authority.transform = change
    reviewer = ScriptedReviewer(PASS)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert not reviewer.tasks and run.pause_reason == "needs_configuration" and "review" not in run.context


@pytest.mark.asyncio
async def test_spec_claim_runs_one_reviewer_and_never_changes_producer_snapshot(db, monkeypatch, spec_registry):
    run, _ = await prepared_spec(db, monkeypatch)
    frozen = copy.deepcopy(run.context["outputs"]["spec"])
    contender = ScriptedReviewer(PASS)

    async def during():
        assert await run_due_reviews(db, model_factory=contender.factory) == 0
    reviewer = ScriptedReviewer(PASS, during=during)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert len(reviewer.tasks) == 1 and not contender.tasks
    assert run.context["outputs"]["spec"] == frozen
    assert run.status == "completed"
