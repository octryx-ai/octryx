"""Confirmed publication audiences stay pinned at dispatch and receipt issue."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import DocumentationAudienceReceipt, Project
from app.services.workflow_runs.documentation import audience_contract, receipt_record
from app.services.workflow_runs.documentation import audience_receipt as receipts
from app.services.workflow_runs.documentation.write_intent import approve_publication_intent, publication_body_hash
from app.services.workflow_runs.pause import payload_hash
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_outsider
from tests.s1_publish_cloud_support import FakeCloudV2
from tests.s1_publish_run_support import confirm, documented_run, publish, reserve
from tests.s1_receipt_flow_support import bind_publication

pytestmark = pytest.mark.asyncio
DRIFT_FIELDS = ("semantics", "principal_user_id", "outsider_user_id", "source_key", "workspace_id", "missing")


async def _change_config(db, run, field):
    project = await db.get(Project, run.project_id)
    docs = dict(project.config["feature_documentation"])
    proof = dict(docs["audience_proof"])
    if field == "semantics":
        proof[field] = "source_restricted"
    elif field == "principal_user_id":
        proof[field] = await seed_member(db, workspace_id=run.project_id, role="member")
    elif field == "outsider_user_id":
        proof[field] = await seed_outsider(db)
    elif field == "source_key":
        proof[field] = "different-connector"
    docs["audience_proof"] = proof
    project.config = {**project.config, "feature_documentation": docs}
    await db.commit()


def _change_card(decision, field):
    payload = dict(decision.payload)
    if field == "missing":
        payload.pop("audience", None)
    elif field == "workspace_id":
        payload["audience"] = {**payload["audience"], field: "different-workspace"}
    decision.payload, decision.payload_hash = payload, payload_hash(payload)


@pytest.mark.parametrize("field", DRIFT_FIELDS)
async def test_audience_drift_or_missing_snapshot_refuses_before_any_claim_or_provider_write(db, field):
    cloud = FakeCloudV2()
    run = await documented_run(db)
    intent = await reserve(db, run, cloud)
    decision = await confirm(db, run, intent, approve=False)
    if field in ("workspace_id", "missing"):
        _change_card(decision, field)
    await db.flush()
    await approve_publication_intent(
        db, run, decision_id=decision.id, card_hash=decision.payload_hash,
        output_hash=decision.payload["output_hash"], body_hash=publication_body_hash(decision.payload["body"]))
    await db.commit()
    if field not in ("workspace_id", "missing"):
        await _change_config(db, run, field)
    before = len(cloud.requests)
    outcome = await publish(db, run, cloud)
    assert not outcome.ok and outcome.failure_class == "target_drift"
    assert "audience" in outcome.reason
    assert cloud.writes == [] and len(cloud.requests) == before
    await db.refresh(intent)
    assert intent.state == "approved" and intent.claimed_by is None


@pytest.mark.parametrize("field", DRIFT_FIELDS)
async def test_audience_drift_or_missing_snapshot_never_issues_new_challenge(db, field):
    runtime, _, evidence_index = build_runtime()
    bound = await bind_publication(db, runtime, evidence_index)
    if field in ("workspace_id", "missing"):
        _change_card(bound.decision, field)
        bound.intent.card_hash = bound.decision.payload_hash
        await db.commit()
    else:
        await _change_config(db, bound.run, field)
    with pytest.raises(audience_contract.AudienceProofError, match="audience"):
        await receipts.issue_audience_challenge(db, bound.run)
    assert (await db.execute(select(DocumentationAudienceReceipt))).scalars().all() == []


async def test_unchanged_confirmed_audience_publishes_once_and_issues_exact_actor_challenge(db):
    cloud = FakeCloudV2()
    run = await documented_run(db)
    intent = await reserve(db, run, cloud)
    await confirm(db, run, intent)
    outcome = await publish(db, run, cloud)
    assert outcome.ok and len(cloud.writes) == 1
    # Receipt proof uses its own real Knowledge-ledger fixture; no provider or search is faked as proof.
    runtime, _, evidence_index = build_runtime()
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    assert receipt.expected_principal_id == bound.decision.payload["audience"]["principal_user_id"]
    assert receipt.publication_card_hash == bound.decision.payload_hash


async def test_receipt_rejects_other_actual_connector_even_when_card_and_current_config_match(db):
    runtime, _, evidence_index = build_runtime()
    bound = await bind_publication(db, runtime, evidence_index)
    project = await db.get(Project, bound.workspace)
    docs = dict(project.config["feature_documentation"])
    docs["audience_proof"] = {**docs["audience_proof"], "source_key": "other-configured-source"}
    project.config = {**project.config, "feature_documentation": docs}
    bound.decision.payload = {**bound.decision.payload, "audience": {
        **bound.decision.payload["audience"], "source_key": "other-configured-source"}}
    bound.decision.payload_hash = payload_hash(bound.decision.payload)
    bound.intent.card_hash = bound.decision.payload_hash
    await db.commit()
    with pytest.raises(audience_contract.AudienceProofError):
        await receipts.issue_audience_challenge(db, bound.run)
    assert (await db.execute(select(DocumentationAudienceReceipt))).scalars().all() == []


@pytest.mark.parametrize("field", DRIFT_FIELDS)
@pytest.mark.parametrize("stage", ("record", "consume"))
async def test_existing_challenge_is_revoked_when_approved_audience_drifts(db, field, stage):
    runtime, _, evidence_index = build_runtime()
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    principal = await fetch_user(db, bound.principal)
    request = {"challenge_id": receipt.challenge_id}
    if stage == "consume":
        recorded = await receipt_record.record_audience_receipt(
            db, current_user=principal, workspace_id=bound.workspace, proof_request=request, runtime=runtime)
        assert recorded["state"] == "recorded"
        await db.commit()
    if field in ("workspace_id", "missing"):
        _change_card(bound.decision, field)
        bound.intent.card_hash = bound.decision.payload_hash
        await db.commit()
    else:
        await _change_config(db, bound.run, field)
    if stage == "record":
        with pytest.raises(audience_contract.AudienceProofError):
            await receipt_record.record_audience_receipt(
                db, current_user=principal, workspace_id=bound.workspace, proof_request=request, runtime=runtime)
    else:
        outcome = await receipts.consume_audience_receipt(db, bound.run)
        assert not outcome.ok and outcome.failure_class == "audience_unproven"
    await db.refresh(receipt)
    assert receipt.state == "revoked" and receipt.consumed_at is None
    assert (await db.execute(select(DocumentationAudienceReceipt))).scalars().all() == [receipt]
