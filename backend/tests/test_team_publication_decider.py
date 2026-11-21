"""S1 publication authorisation remains bound to its original human decision node.

Real role/membership services and publication executor, isolated fixture DB and Cloud transport.
The confirming actor differs from the requester, who retains governed execution/tool identity.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update

from app.models import AuditLog, FlowDefinition, FlowDefinitionVersion, User
from app.models.security.user import UserProject
from app.services.workflow_runs.documentation.decision_authority import publication_decision_problem
from app.services.workflow_runs.documentation.publication_checks import _approved_body
from app.services.workflow_runs.documentation.write_intent import (
    PublicationIntentError,
    approve_publication_intent,
    publication_body_hash,
)
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.s1_publish_cloud_support import FakeCloudV2
from tests.s1_publish_run_support import confirm, documented_run, publish, reserve
from tests.work_role_support import assign_seed_role, set_seed_role_active

pytestmark = pytest.mark.asyncio


async def setup_publication(db, *, requester=False):
    cloud = FakeCloudV2()
    run = await documented_run(db)
    run.context = {**run.context, "execution_identity": run.requested_by}
    admin = await fetch_user(db, await seed_member(db, workspace_id=run.project_id, role="admin"))
    owner = await fetch_user(db, await seed_member(db, workspace_id=run.project_id, role="member"))
    role = await assign_seed_role(db, run.project_id, "doc_owner", user_id=owner.id)
    config = {"subject": "publication", "decider": "requester" if requester else "role:doc_owner"}
    flow = FlowDefinition(key=f"publish-role-{uuid.uuid4().hex}", name="Publish role fixture",
        project_id=run.project_id, status="published", created_by=admin.id)
    db.add(flow)
    await db.flush()
    version = FlowDefinitionVersion(flow_id=flow.id, status="published", created_by=admin.id,
        definition_json={"execution_kind": "phased", "nodes": [
            {"id": "start", "type": "start"},
            {"id": "confirm_publication", "type": "user_confirmation", "config": config},
            {"id": "publish_docs", "type": "platform_action", "config": {"action": "documentation.publish"}},
            {"id": "done", "type": "outcome", "config": {"outcome": "done"}}], "edges": [
            {"id": "start", "source_node_id": "start", "target_node_id": "confirm_publication"},
            {"id": "confirmed", "source_node_id": "confirm_publication", "target_node_id": "publish_docs", "when": "confirmed"},
            {"id": "done", "source_node_id": "publish_docs", "target_node_id": "done", "when": "succeeded"}]})
    db.add(version)
    await db.flush()
    flow.current_version_id = version.id
    run.flow_definition_version_id = version.id
    await db.commit()
    intent = await reserve(db, run, cloud)
    decision = await confirm(db, run, intent, approve=False)
    decision.decided_by = run.requested_by if requester else owner.id
    await db.commit()
    return SimpleNamespace(run=run, cloud=cloud, intent=intent, decision=decision, owner=owner,
                           admin=admin, role=role)


async def approve(db, case):
    return await approve_publication_intent(db, case.run, decision_id=case.decision.id,
        card_hash=case.decision.payload_hash, output_hash=case.decision.payload["output_hash"],
        body_hash=publication_body_hash(case.decision.payload["body"]))


@pytest.mark.parametrize("requester", [False, True])
async def test_original_authorised_human_approves_and_publishes_after_run_moves_nodes(db, requester):
    case = await setup_publication(db, requester=requester)
    before = list((await db.execute(select(AuditLog.id, AuditLog.user_id))).all())
    await approve(db, case)
    await db.commit()
    case.run.current_node_id = "publish_docs"
    await db.commit()
    assert await publication_decision_problem(db, case.run, case.decision) == ""
    body, problem = await _approved_body(db, case.run, case.intent)
    assert body == case.decision.payload["body"] and problem == ""
    assert list((await db.execute(select(AuditLog.id, AuditLog.user_id))).all()) == before
    outcome = await publish(db, case.run, case.cloud)
    assert outcome.ok, outcome.reason
    assert len(case.cloud.writes) == 1
    assert case.run.requested_by == case.run.context["execution_identity"]
    assert case.decision.decided_by == (case.run.requested_by if requester else case.owner.id)
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "s1.documentation.published",
        AuditLog.resource_id == case.intent.id))).scalar_one()
    assert audit.user_id == case.run.requested_by


@pytest.mark.parametrize("revoke", ["role", "membership", "inactive", "service"])
@pytest.mark.parametrize("stage", ["approve", "dispatch"])
async def test_revoked_publication_authority_refuses_before_sender_claim_or_provider_io(db, revoke, stage):
    case = await setup_publication(db)
    if stage == "dispatch":
        await approve(db, case)
        await db.commit()
    if revoke == "role":
        await set_seed_role_active(db, case.role, False)
    elif revoke == "membership":
        await db.execute(delete(UserProject).where(UserProject.user_id == case.owner.id,
            UserProject.project_id == case.run.project_id))
    else:
        await db.execute(update(User).where(User.id == case.owner.id).values(
            **({"is_active": False} if revoke == "inactive" else {"account_type": "service"})))
    await db.commit()
    before = len(case.cloud.requests)
    if stage == "approve":
        with pytest.raises(PublicationIntentError):
            await approve(db, case)
    else:
        outcome = await publish(db, case.run, case.cloud)
        assert not outcome.ok and outcome.failure_class == "safety"
    await db.refresh(case.intent)
    assert case.intent.state == ("reserved" if stage == "approve" else "approved")
    assert case.intent.claimed_by is None and case.cloud.writes == []
    assert len(case.cloud.requests) == before


@pytest.mark.parametrize("field,value", [
    ("node_id", "publish_docs"), ("node_id", "unknown"), ("subject", "advance"),
    ("kind", "approval"), ("action", "changed"), ("decided_by", None),
])
async def test_exact_stored_publication_decision_and_original_node_are_required(db, field, value):
    case = await setup_publication(db)
    setattr(case.decision, field, value)
    await db.commit()
    assert await publication_decision_problem(db, case.run, case.decision)
    with pytest.raises(PublicationIntentError):
        await approve(db, case)
    assert case.intent.state == "reserved"


async def test_pinned_graph_authority_never_uses_current_publish_node_or_requester_as_fallback(db):
    case = await setup_publication(db)
    case.decision.decided_by = case.run.requested_by
    await db.commit()
    assert await publication_decision_problem(db, case.run, case.decision)
    with pytest.raises(PublicationIntentError):
        await approve(db, case)
    case.decision.decided_by = case.owner.id
    case.run.flow_definition_version_id = None
    await db.commit()
    assert await publication_decision_problem(db, case.run, case.decision)


async def test_exact_target_and_hash_checks_remain_required_for_role_approvals(db):
    case = await setup_publication(db)
    with pytest.raises(PublicationIntentError, match="card hash"):
        await approve_publication_intent(db, case.run, decision_id=case.decision.id, card_hash="sha256:stale",
            output_hash=case.decision.payload["output_hash"], body_hash=publication_body_hash(case.decision.payload["body"]))
    target = {**case.decision.payload["target"], "space_id": "foreign-space"}
    case.decision.payload = {**case.decision.payload, "target": target}
    await db.commit()
    with pytest.raises(PublicationIntentError, match="card hash|space_id"):
        await approve(db, case)
    assert case.intent.state == "reserved"


async def test_membership_is_rechecked_after_acquiring_original_decider_locks(db, monkeypatch):
    from app.services.workflow_runs.documentation import decision_authority

    case = await setup_publication(db)
    original = decision_authority.lock_actor_membership

    async def revoke_after_lock(*args, **kwargs):
        await original(*args, **kwargs)
        await db.execute(delete(UserProject).where(UserProject.user_id == case.owner.id,
            UserProject.project_id == case.run.project_id))
        await db.flush()

    monkeypatch.setattr(decision_authority, "lock_actor_membership", revoke_after_lock)
    assert "authority changed" in await publication_decision_problem(db, case.run, case.decision)
    assert case.intent.state == "reserved" and case.intent.claimed_by is None
    assert case.cloud.writes == []


async def test_foreign_run_decision_never_authorises_this_intent(db):
    case = await setup_publication(db)
    other = await documented_run(db)
    case.decision.run_id = other.id
    await db.commit()
    assert await publication_decision_problem(db, case.run, case.decision)
    with pytest.raises(PublicationIntentError):
        await approve(db, case)
    assert case.intent.state == "reserved" and case.cloud.writes == []


@pytest.mark.parametrize("stage", ["approve", "dispatch"])
@pytest.mark.parametrize("corruption", ["hash", "body"])
async def test_stored_card_hash_and_body_corruption_never_authorise_a_send(db, stage, corruption):
    case = await setup_publication(db)
    if stage == "dispatch":
        await approve(db, case)
        await db.commit()
    # Deliberately persist a hash that no longer hashes this payload. Matching the intent's hash
    # is insufficient: the stored confirmed payload must also prove its own hash independently.
    if corruption == "hash":
        case.decision.payload_hash = "sha256:" + "0" * 64
        if stage == "dispatch":
            case.intent.card_hash = case.decision.payload_hash
    else:
        case.decision.payload = {**case.decision.payload, "body": case.decision.payload["body"] + "<p>Unconfirmed replacement.</p>"}
    await db.commit()
    assert await publication_decision_problem(db, case.run, case.decision) == (
        "the confirmed target and body do not bind their card hash")
    before = len(case.cloud.requests)
    if stage == "approve":
        with pytest.raises(PublicationIntentError, match="confirmed target and body"):
            await approve(db, case)
    else:
        outcome = await publish(db, case.run, case.cloud)
        assert not outcome.ok and outcome.failure_class == "safety"
        assert "card hash" in outcome.reason
    await db.refresh(case.intent)
    assert case.intent.state == ("reserved" if stage == "approve" else "approved")
    assert case.intent.claimed_by is None
    assert case.cloud.writes == [] and len(case.cloud.requests) == before
