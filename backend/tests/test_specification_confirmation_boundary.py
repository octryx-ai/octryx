"""Actual canonical producer, Knowledge ledger, native review and HTTP confirmer boundary."""
from __future__ import annotations

import copy
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.models import FlowDefinition, User, UserProject, WorkflowRunDecision
from app.models.project.knowledge_evidence import KnowledgeSourceHead
from app.models.project.knowledge_source_acl import KnowledgeSourceAcl, KnowledgeSourceAclPrincipal
from app.services.auth.tokens import create_access_token
from app.services.knowledge.access.acl_keys import principal_key_for_email
from app.services.knowledge.access.source_acl import restrict_source
from app.services.workflow_checks.library import ToolUse, TurnEvidence
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import RUN_RESOLUTION_KEY, record_phase_turn
from app.services.workflow_runs.review.runner import run_due_reviews
from app.services.workflow_runs.specification.lineage import canonicalize_output, take_output_provenance
from tests.phased_workflow_fixtures import publish_phased
from tests.specification_definition_support import specification_definition
from tests.specification_producer_support import SPEC, enter, producer, put
from tests.workflow_artefact_review_support import PASS
from tests.workflow_run_review_support import ScriptedReviewer


def headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def decisions(db, run):
    return await db.scalar(select(func.count()).select_from(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id))


async def reviewed_spec(db, *, restricted=False, verdict=PASS):
    # Existing helper creates real canonical refs/ledger/calls using an ordinary current principal.
    # Its original hypothesis graph is a data scaffold; bind an actually published new graph before review.
    run, actor, session, source, revision, call, kwargs, brief = await producer(db, complete=not restricted)
    if restricted:
        db.add_all([
            KnowledgeSourceAcl(project_id=run.project_id, source_key=source.source_key, restriction="restricted"),
            KnowledgeSourceAclPrincipal(project_id=run.project_id, source_key=source.source_key,
                                        principal_key=principal_key_for_email(actor.email))])
        await db.flush()
        canonical = await canonicalize_output(db, run, "research_brief", brief, **kwargs)
        proof = take_output_provenance(db, run, "research_brief", canonical,
                                      session_id=session.id, request_id=kwargs["request_id"])
        await put(db, run, "research_brief", canonical, proof=proof)
        await enter(db, run, "draft")
        proposal = copy.deepcopy(SPEC)
        proposal["claims"][0]["evidence_keys"] = [call.parameters["evidence_key"]]
        await put(db, run, "spec", await canonicalize_output(db, run, "spec", proposal, principal=actor))
    key = await publish_phased(db, specification_definition())
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    run.flow_definition_version_id, run.workflow_key = flow.current_version_id, key
    run.status, run.waiting_kind = "running", None
    await db.flush()
    marker = {"run_id": run.id, "node_id": "draft", "entry": run.node_state["entry"]}
    await record_phase_turn(db, request_analysis={ROUTING_RESOLUTION_KEY: {RUN_RESOLUTION_KEY: marker}},
        session_id=session.id, state="passed", results=[], evidence=TurnEvidence(tools=[ToolUse("submit_spec", True)]))
    await db.commit()
    assert run.current_node_id == "review" and run.waiting_kind == "awaiting_review"
    reviewer = ScriptedReviewer(verdict)  # Only model answer is scripted; every authority/resolver/ledger path is real.
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    await db.refresh(run)
    if verdict["verdict"] == "pass":
        assert (run.status, run.current_node_id) == ("waiting", "confirm-spec"), (run.status, run.pause_reason, run.last_error)
        assert run.context["review"]["verdict"] == "pass" and run.gate_results["spec-ready"]["state"] == "passed"
    else:
        assert (run.status, run.current_node_id) == ("running", "draft")
        assert run.gate_results["spec-ready"]["state"] == "failed"
    assert "Observed: tests passed" in reviewer.tasks[0][1]
    return run, actor, source, revision, call


async def get_view(client, run, actor):
    response = await client.get(f"/api/v1/workflow-runs/{run.id}", headers=headers(actor))
    assert response.status_code == 200, response.text
    return response.json()["run"]


def assert_withheld(view, source, revision, call):
    for waiting in (view["waiting"], view["node_state"]["waiting"]):
        assert waiting["payload"].get("output") is None
        assert waiting["payload"].get("missing") and waiting["payload_hash"] is None
    public = json.dumps(view)
    for secret in (source.id, revision.id, call.id, call.parameters["evidence_key"], "Observed: tests passed"):
        assert secret not in public


async def assert_mcp_withheld(db, run, actor, source, revision, call):
    from app.services.mcp_governed_knowledge import McpCaller
    from app.services.mcp_workflow_run_tools import mcp_workflow_run_status

    caller = McpCaller(user_id=actor.id, grant_id=None, scopes=("knowledge:read",),
                       bound_project_ids=(run.project_id,), workspace_header=run.project_id)
    result = await mcp_workflow_run_status(db, caller=caller, user=actor, workspace_id=run.project_id,
                                           arguments={"run_id": run.id})
    assert result["state"] == "ok"
    waiting = result["workflow_run"]["decision"]
    assert waiting["payload"].get("output") is None and waiting["payload"].get("missing")
    assert not waiting["payload_hash"] and "confirm" not in waiting["actions"]
    public = json.dumps(result)
    assert all(value not in public for value in (
        source.id, revision.id, call.id, call.parameters["evidence_key"], "Observed: tests passed"))


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["acl", "head"])
async def test_review_pass_does_not_authorize_revoked_or_stale_actual_confirmer(db, client, drift):
    run, actor, source, revision, call = await reviewed_spec(db)
    old_hash = run.node_state["waiting"]["payload_hash"]
    before = copy.deepcopy((run.current_node_id, run.context["outputs"], run.loop_counters))
    count = await decisions(db, run)
    if drift == "acl":
        await restrict_source(db, project_id=run.project_id, source_key=source.source_key, restriction="restricted")
    else:
        head = await db.get(KnowledgeSourceHead, source.id)
        head.wanted_revision_id = None
    await db.commit()
    assert_withheld(await get_view(client, run, actor), source, revision, call)
    await assert_mcp_withheld(db, run, actor, source, revision, call)
    response = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=headers(actor),
        json={"action": "confirm", "payload_hash": old_hash})
    assert response.status_code == 409, response.text
    assert all(value not in response.text for value in (source.id, revision.id, call.id, "Observed: tests passed"))
    await db.refresh(run)
    assert await decisions(db, run) == count
    assert (run.current_node_id, run.context["outputs"], run.loop_counters) == before
    assert run.status == "waiting"
    assert_withheld(await get_view(client, run, actor), source, revision, call)
    await assert_mcp_withheld(db, run, actor, source, revision, call)


@pytest.mark.asyncio
async def test_preview_then_revoke_before_post_rechecks_actual_principal_under_claim(db, client):
    run, actor, source, revision, call = await reviewed_spec(db)
    preview = await get_view(client, run, actor)
    assert preview["waiting"]["payload"]["output"]["hash"] == run.context["outputs"]["spec"]["hash"]
    assert "Observed: tests passed" in json.dumps(preview)
    card_hash = preview["waiting"]["payload_hash"]
    count = await decisions(db, run)
    before = copy.deepcopy((run.context["outputs"], run.loop_counters))
    await restrict_source(db, project_id=run.project_id, source_key=source.source_key, restriction="restricted")
    await db.commit()
    response = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=headers(actor),
        json={"action": "confirm", "payload_hash": card_hash})
    assert response.status_code == 409, response.text
    assert all(value not in response.text for value in (source.id, revision.id, call.id, "Observed: tests passed"))
    await db.refresh(run)
    assert await decisions(db, run) == count and run.current_node_id == "confirm-spec"
    assert (run.context["outputs"], run.loop_counters) == before
    assert_withheld(await get_view(client, run, actor), source, revision, call)
    await assert_mcp_withheld(db, run, actor, source, revision, call)


@pytest.mark.asyncio
async def test_other_workspace_viewer_cannot_borrow_requester_source_or_confirmation_authority(db, client):
    run, actor, source, revision, call = await reviewed_spec(db, restricted=True)
    other = User(id=str(uuid.uuid4()), username=f"spec-denied-{uuid.uuid4().hex[:8]}", email="denied@example.test",
                 password_hash="test-only-not-a-login", account_type="human", is_active=True)
    db.add_all([other, UserProject(user_id=other.id, project_id=run.project_id, role="viewer")])
    await db.commit()
    owner_view = await get_view(client, run, actor)
    assert owner_view["waiting"]["payload"]["output"]["hash"] == run.context["outputs"]["spec"]["hash"]
    assert_withheld(await get_view(client, run, other), source, revision, call)
    await assert_mcp_withheld(db, run, other, source, revision, call)
    count = await decisions(db, run)
    response = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=headers(other),
        json={"action": "confirm", "payload_hash": owner_view["waiting"]["payload_hash"]})
    assert response.status_code == 403, response.text
    assert await decisions(db, run) == count
    await db.refresh(run)
    assert run.current_node_id == "confirm-spec" and run.status == "waiting"


@pytest.mark.asyncio
async def test_unchanged_permitted_requester_confirms_exact_reviewed_spec_once(db, client):
    run, actor, _, _, _ = await reviewed_spec(db)
    view = await get_view(client, run, actor)
    card_hash = view["waiting"]["payload_hash"]
    frozen = copy.deepcopy(run.context["outputs"]["spec"])
    count = await decisions(db, run)
    response = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=headers(actor),
        json={"action": "confirm", "payload_hash": card_hash})
    assert response.status_code == 200, response.text
    await db.refresh(run)
    assert (run.status, run.outcome) == ("completed", "done")
    assert run.context["outputs"]["spec"] == frozen and await decisions(db, run) == count + 1
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id,
        WorkflowRunDecision.node_id == "confirm-spec"))).scalar_one()
    assert decision.decided_by == actor.id and decision.payload_hash == card_hash and decision.action == "confirmed"
    again = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=headers(actor),
        json={"action": "confirm", "payload_hash": card_hash})
    assert again.status_code == 409 and await decisions(db, run) == count + 1


@pytest.mark.asyncio
async def test_rework_native_status_authorizes_review_source_quotes_as_actual_current_viewer(db, client):
    from app.services.knowledge.access.authorization import authorize_workspace
    from app.services.knowledge.ledger.errors import EvidenceLedgerError
    from app.services.knowledge.ledger.reading import read_span_window
    from app.services.mcp_governed_knowledge import McpCaller
    from app.services.mcp_workflow_run_tools import mcp_workflow_run_status
    from app.services.workflow_runs.octryx.contract import run_contract
    from tests.knowledge_evidence_seed_support import fetch_user, seed_member

    quote = "Observed: tests passed; the cause is unproved."
    changes = {"verdict": "changes", "summary": "Clarify the observation", "findings": [
        {"severity": "medium", "field_or_claim_id": "CL1", "reason": quote,
         "requested_change": "Disclose uncertainty"}]}
    run, actor, source, _, call = await reviewed_spec(db, verdict=changes)

    async def native(user):
        return await mcp_workflow_run_status(db, caller=McpCaller(user_id=user.id, grant_id=None,
            scopes=("knowledge:read",), workspace_header=run.project_id), user=user, workspace_id=run.project_id,
            arguments={"run_id": run.id})

    permitted = await native(actor)
    assert quote in json.dumps(permitted["workflow_run"]["phase"]["review_findings"])
    assert permitted["workflow_run"]["phase"]["inputs"]["research_brief"]["evidence"]
    unbound = await run_contract(db, run)
    assert quote not in json.dumps(unbound) and not unbound["phase"]["inputs"]
    other = await fetch_user(db, await seed_member(db, workspace_id=run.project_id, role="viewer"))
    await restrict_source(db, project_id=run.project_id, source_key=source.source_key, restriction="restricted")
    await db.commit()
    for actual in (actor, other):
        authorized = await authorize_workspace(db, current_user=actual, workspace_id=run.project_id)
        with pytest.raises(EvidenceLedgerError):
            await read_span_window(db, authorized=authorized, evidence_key=call.parameters["evidence_key"], window=0)
        result = await native(actual)
        phase = result["workflow_run"]["phase"]
        assert quote not in json.dumps(result) and not phase["inputs"]
        assert not phase["findings"] and not phase["review_findings"]
        assert not {"knowledge_read", "knowledge_search"}.intersection(phase["tools"]["allow"])
        view = await get_view(client, run, actual)
        assert quote not in json.dumps(view)  # Plain run gate projection must also withhold quoted findings.
