"""Actual non-admin sender/receiver, typed provenance and atomic handoff authority."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    FlowDefinition,
    Session,
    ToolCall,
    UserProject,
    WorkflowRun,
    WorkflowRunDecision,
    WorkflowRunSession,
)
from app.models.project.knowledge_evidence import KnowledgeSourceHead
from app.models.project.knowledge_source_acl import KnowledgeSourceAcl, KnowledgeSourceAclPrincipal
from app.models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse
from app.services.knowledge.access.acl_keys import principal_key_for_email
from app.services.workflow_runs.handoff import service
from app.services.workflow_runs.handoff.allocation import allocate_child
from app.services.workflow_runs.handoff.permissions import rights_evaluator
from app.services.workflow_runs.handoff.specification import has_spec_handoff, resolve_accepted_spec
from app.services.workflow_runs.phase_outputs import output_hash
from app.services.workflow_runs.records import WorkflowRunError
from app.services.workflow_runs.specification.lineage import canonicalize_output, take_output_provenance
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.phased_workflow_fixtures import publish_phased
from tests.specification_definition_support import BUDGET
from tests.specification_producer_support import BRIEF, IDEA, PLAN, SPEC, enter, producer, put
from tests.team_handoff_support import action, counts, setup_case

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def tables(db):
    connection = await db.connection()
    await connection.run_sync(lambda bind: [table.create(bind, checkfirst=True) for table in
        (WorkflowHandoff.__table__, WorkflowHandoffResponse.__table__)])


async def same_scope_producer(db, case):
    """A second independent canonical producer in the same real source scope/principal, not a copied envelope."""
    parent = WorkflowRun(project_id=case.parent.project_id, workflow_kind="phased", workflow_key=case.parent.workflow_key,
        flow_definition_version_id=case.parent.flow_definition_version_id, requested_by=case.sender.id,
        status="running", state_version=0, node_state={"entry": 0}, context={}, limits={"budget": dict(BUDGET)})
    session = Session(user_id=case.sender.id, project_id=parent.project_id, origin="chat")
    db.add_all([parent, session])
    await db.flush()
    db.add(WorkflowRunSession(run_id=parent.id, session_id=session.id, role="main", active=True))
    await enter(db, parent, "idea")
    await put(db, parent, "idea_frame", await canonicalize_output(
        db, parent, "idea_frame", IDEA, principal=case.sender), confirm=True)
    await enter(db, parent, "plan")
    await put(db, parent, "research_plan", await canonicalize_output(
        db, parent, "research_plan", PLAN, principal=case.sender), confirm=True)
    await enter(db, parent, "research")
    key = case.call.parameters["evidence_key"]
    call = ToolCall(session_id=session.id, tool_name="knowledge_read", parameters={"evidence_key": key},
                    result={"state": "ok", "evidence_key": key}, status="success", request_id="second-research-turn")
    db.add(call)
    await db.flush()
    kwargs = {"principal": case.sender, "session_id": session.id, "request_id": call.request_id, "tool_history": [
        {"tool_name": "knowledge_read", "persisted_call_id": call.id, "result": {"state": "ok"}}]}
    brief = copy.deepcopy(BRIEF)
    brief["claims"][0]["evidence_keys"] = [key]
    return parent, case.sender, session, case.source, case.revision, call, kwargs, brief


async def prepared_spec_case(db, *, criteria=None, receiver_access=True, shared=None, members=()):
    """Real typed producer/ledger and human decisions, before any offer; no authority doubles.

    ``members``: further ordinary viewers seeded before the brief, each ``True`` with source ACL access.
    """
    parent, sender, session, source, revision, call, kwargs, brief = (
        await same_scope_producer(db, shared) if shared is not None else await producer(db, complete=False))
    receiver = shared.receiver if shared else await fetch_user(
        db, await seed_member(db, workspace_id=parent.project_id, role="viewer"))
    extra = [await fetch_user(db, await seed_member(db, workspace_id=parent.project_id, role="viewer"))
             for _ in members]
    if shared is None:
        db.add(KnowledgeSourceAcl(project_id=parent.project_id, source_key=source.source_key, restriction="restricted"))
        granted = [user for user, access in zip(extra, members, strict=True) if access]
        for actor in [sender, *([receiver] if receiver_access else []), *granted]:
            db.add(KnowledgeSourceAclPrincipal(project_id=parent.project_id, source_key=source.source_key,
                                              principal_key=principal_key_for_email(actor.email)))
    await db.flush()
    canonical = await canonicalize_output(db, parent, "research_brief", brief, **kwargs)
    proof = take_output_provenance(db, parent, "research_brief", canonical,
                                  session_id=session.id, request_id=kwargs["request_id"])
    await put(db, parent, "research_brief", canonical, proof=proof)
    await enter(db, parent, "draft")
    proposal = copy.deepcopy(SPEC)
    proposal["claims"][0]["evidence_keys"] = [call.parameters["evidence_key"]]
    if criteria is not None:
        proposal["criteria"] = copy.deepcopy(criteria)
    await put(db, parent, "spec", await canonicalize_output(db, parent, "spec", proposal, principal=sender), confirm=True)
    await enter(db, parent, "offer")
    # This test pins a published, valid child, without executing it or inventing an engineering grant.
    key = await publish_phased(db, {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"}, {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "done", "source_node_id": "start", "target_node_id": "done"}]})
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    parent.status, parent.waiting_kind = "running", None
    scope = {"workspace_id": parent.project_id, "work_item_id": parent.work_item_id, "repository": parent.repository,
             "service_ids": [], "connection_ids": [], "source_ids": [source.id]}
    contract = {"schema_version": "handoff/v1", "owner": f"person:{receiver.id}", "artefacts": ["spec"],
        "acceptance": "Implement the exact confirmed specification", "scope": scope,
        "detach": False, "timeout_seconds": 300, "deputy": None}
    await db.flush()
    return SimpleNamespace(parent=parent, sender=sender, receiver=receiver, source=source, revision=revision,
        call=call, scope=scope, contract=contract, descriptor={"workflow_key": key, "version_id": flow.current_version_id},
        members=extra)


async def offer(db, case):
    case.row = await service.offer_handoff(db, case.parent, node_id="offer", contract=case.contract,
                                          child_descriptor=case.descriptor)
    await db.flush()
    return case.row


async def accepted_spec_case(db, *, criteria=None, receiver_access=True):
    """Reusable actual accepted parent+child fixture for the engineering criteria consumer."""
    case = await prepared_spec_case(db, criteria=criteria, receiver_access=receiver_access)
    await offer(db, case)
    case.action = action(case.row)
    case.binding = await service.accept_handoff(db, case.row.id, case.receiver, case.action,
                                               rights_evaluator=rights_evaluator, allocator=allocate_child)
    case.child = await db.get(WorkflowRun, case.binding["child_run_id"])
    await db.flush()
    return case


async def test_actual_receiver_consumes_exact_parent_spec_without_local_outputs_or_grants(db):
    case = await accepted_spec_case(db)
    snapshot = await resolve_accepted_spec(db, case.child, principal=case.receiver)
    proof = case.row.envelopes["spec"]
    assert snapshot["envelope"] == proof["envelope"]
    assert snapshot["confirmation"] == {key: proof[key] for key in ("decision_id", "decision_hash", "decided_by")}
    assert snapshot["confirmation"]["decided_by"] == case.sender.id
    assert snapshot["accepted_binding"] == case.binding
    assert snapshot["binding"]["parent_run_id"] == case.parent.id
    assert snapshot["binding"]["principal_user_id"] == case.receiver.id
    assert snapshot["evidence"][0]["call_id"] == case.call.id
    assert snapshot["evidence"][0]["revision_id"] == case.revision.id
    assert snapshot["upstream"]["research_brief"]["hash"] == snapshot["binding"]["research_brief_ref"]["hash"]
    assert not case.child.context.get("outputs")
    assert await has_spec_handoff(db, case.child)
    snapshot["envelope"]["record"]["criteria"].clear()
    assert (await resolve_accepted_spec(db, case.child, principal=case.receiver))["envelope"]["record"]["criteria"]


async def test_sender_permission_cannot_allocate_or_disclose_for_denied_receiver(db):
    case = await prepared_spec_case(db, receiver_access=False)
    await offer(db, case)
    before = await counts(db)
    with pytest.raises(HTTPException) as error:
        await service.preview_handoff(db, case.row.id, case.receiver, rights_evaluator=rights_evaluator)
    assert error.value.detail["reason"] == "needs_configuration"
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, case.row.id, case.receiver, action(case.row),
                                     rights_evaluator=rights_evaluator, allocator=allocate_child)
    assert await counts(db) == before and case.row.state == "offered" and case.row.child_run_id is None


@pytest.mark.parametrize("drift", ["sender_acl", "source_scope", "parent_pass", "confirmation", "terminal"])
async def test_offer_requires_current_actual_sender_and_exact_approved_source_scope(db, drift):
    case = await prepared_spec_case(db)
    if drift == "sender_acl":
        principal = (await db.execute(select(KnowledgeSourceAclPrincipal).where(
            KnowledgeSourceAclPrincipal.principal_key == principal_key_for_email(case.sender.email)))).scalar_one()
        await db.delete(principal)
    elif drift == "source_scope":
        case.contract["scope"]["source_ids"] = []
    elif drift == "parent_pass":
        await enter(db, case.parent, "draft")
        await enter(db, case.parent, "offer")
    elif drift == "confirmation":
        db.add(WorkflowRunDecision(run_id=case.parent.id, kind="confirmation", subject="spec", action="changed",
                                  payload={}, payload_hash=output_hash({}), decided_by=case.sender.id))
    else:
        case.parent.status = "completed"
    await db.flush()
    before = await counts(db)
    with pytest.raises(HTTPException):
        await offer(db, case)
    assert await counts(db) == before
    assert not (await db.execute(select(WorkflowHandoff).where(
        WorkflowHandoff.parent_run_id == case.parent.id))).scalars().all()


@pytest.mark.parametrize("drift", ["acl", "head", "membership", "epoch", "hash", "copied_record", "confirmation",
                                   "upstream", "missing_marker", "other_principal", "fake_principal", "call", "parent_binding"])
async def test_accepted_child_rechecks_actual_authority_and_full_binding_before_disclosure(db, drift):
    case = await accepted_spec_case(db)
    if drift == "acl":
        principal = (await db.execute(select(KnowledgeSourceAclPrincipal).where(
            KnowledgeSourceAclPrincipal.principal_key == principal_key_for_email(case.receiver.email)))).scalar_one()
        await db.delete(principal)
    elif drift == "head":
        head = await db.get(KnowledgeSourceHead, case.source.id)
        head.wanted_revision_id = None
    elif drift == "membership":
        member = (await db.execute(select(UserProject).where(UserProject.user_id == case.receiver.id,
            UserProject.project_id == case.parent.project_id))).scalar_one()
        await db.delete(member)
    elif drift == "confirmation":
        db.add(WorkflowRunDecision(run_id=case.parent.id, kind="confirmation", subject="spec", action="changed",
                                  payload={}, payload_hash=output_hash({}), decided_by=case.sender.id))
    elif drift == "upstream":
        case.parent.context = copy.deepcopy(case.parent.context)
        case.parent.context["outputs"]["research_brief"]["record"]["summary"] = "Unapproved draft"
    elif drift in {"other_principal", "fake_principal"}:
        pass
    elif drift == "call":
        case.call.request_id = "other-turn"
    elif drift == "parent_binding":
        case.child.parent_node_id = "other-offer"
    else:
        case.child.context = copy.deepcopy(case.child.context)
        if drift == "epoch":
            case.child.context["handoff_binding"]["owner_epoch"] += 1
        elif drift == "hash":
            case.child.context["handoff_binding"]["payload_hash"] = "sha256:" + "0" * 64
        elif drift == "missing_marker":
            del case.child.context["handoff_binding"]
        else:
            case.child.context["handoff"]["spec"]["summary"] = "Unapproved child draft"
    await db.flush()
    before = copy.deepcopy(case.child.context)
    assert await has_spec_handoff(db, case.child)
    with pytest.raises(WorkflowRunError) as error:
        await resolve_accepted_spec(db, case.child, principal=(
            case.sender if drift == "other_principal" else SimpleNamespace(id=case.receiver.id)
            if drift == "fake_principal" else case.receiver))
    assert error.value.code in {"needs_configuration", "stale_owner"}
    assert case.child.context == before and not case.child.context.get("outputs")
    assert "Observed:" not in str(error.value)


@pytest.mark.parametrize("shape", ["spec", ["spec"], {"spec": None}])
async def test_claimed_malformed_spec_never_selects_legacy_fallback(db, shape):
    case = await accepted_spec_case(db)
    case.child.context = {**case.child.context, "handoff_approved_envelopes": shape, "handoff": shape}
    await db.flush()
    assert await has_spec_handoff(db, case.child)
    with pytest.raises(WorkflowRunError):
        await resolve_accepted_spec(db, case.child, principal=case.receiver)


async def test_legacy_non_spec_offer_does_not_become_spec_bound(db):
    case = await setup_case(db)
    assert not await has_spec_handoff(db, case.parent)
    # Old service-only fixture keeps its original allocator/evaluator seam; no spec authority is mocked.
    from tests.team_handoff_support import allocate, rights

    binding = await service.accept_handoff(db, case.row.id, case.p, action(case.row),
                                           rights_evaluator=rights, allocator=allocate)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    assert not await has_spec_handoff(db, child)


async def test_second_current_confirmed_same_scope_parent_cannot_supply_the_accepted_spec(db):
    case = await accepted_spec_case(db)
    second = await prepared_spec_case(db, shared=case)
    second_proof = (await service.confirmed_envelopes(db, second.parent, ["spec"]))["spec"]
    from app.services.workflow_runs.handoff.specification import validate_spec_envelopes

    # The substituted proof is fully canonical/current, not a draft or a broken source.
    assert await validate_spec_envelopes(db, parent=second.parent, actor=case.receiver,
        scope=case.scope, envelopes={"spec": second_proof})
    case.row.envelopes = {"spec": second_proof}
    case.row.payload_hash = service.canonical_hash(service.binding_payload(case.row))
    case.child.context = copy.deepcopy(case.child.context)
    case.child.context["handoff_approved_envelopes"] = copy.deepcopy(case.row.envelopes)
    case.child.context["handoff"]["spec"] = copy.deepcopy(second_proof["envelope"]["record"])
    case.child.context["handoff_binding"]["payload_hash"] = case.row.payload_hash
    await db.flush()
    with pytest.raises(HTTPException) as error:
        await service.preview_handoff(db, case.row.id, case.receiver, rights_evaluator=rights_evaluator)
    assert error.value.detail["reason"] == "needs_configuration"
    with pytest.raises(WorkflowRunError) as error:
        await resolve_accepted_spec(db, case.child, principal=case.receiver)
    assert error.value.code == "needs_configuration"


@pytest.mark.parametrize("envelopes", ["spec", ["spec"], {"spec": None}, {"spec": {"envelope": "spec"}},
    {"spec": {"envelope": {"kind": ["spec"], "record": {}}}}, {}])
async def test_malformed_durable_spec_proof_is_a_safe_configuration_hold(db, envelopes):
    case = await accepted_spec_case(db)
    case.row.envelopes = envelopes
    case.row.payload_hash = service.canonical_hash(service.binding_payload(case.row))
    case.child.context = {**case.child.context, "handoff_binding": {
        **case.child.context["handoff_binding"], "payload_hash": case.row.payload_hash}}
    await db.flush()
    assert await has_spec_handoff(db, case.child)
    with pytest.raises(WorkflowRunError) as error:
        await resolve_accepted_spec(db, case.child, principal=case.receiver)
    assert error.value.code == "needs_configuration"
