"""Refusing or limiting the consume of an audience receipt after the run, card, page version, challenge or role changed."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import delete, update

from app.models import DocumentationAudienceReceipt, WorkflowRun, WorkflowRunDecision
from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
from app.models.security.user import UserProject
from app.services.workflow_runs.documentation import audience_contract
from app.services.workflow_runs.documentation import audience_receipt as receipts
from app.services.workflow_runs.pause import payload_hash
from app.time_utils import utc_now
from tests.knowledge_evidence_seed_support import fetch_user
from tests.s1_receipt_flow_support import (  # noqa: F401
    CRITERIA,
    PAGE_ID,
    as_user,
    bind_publication,
    evidence_runtime,
    make_admin,
    prove,
    standalone_receipt_service,
    state_of,
)

pytestmark = pytest.mark.asyncio


async def test_a_receipt_of_another_run_is_never_consumed(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, receipt.challenge_id)).status_code == 200
    other = WorkflowRun(workflow_kind="phased", workflow_key="b-vnext", requested_by=bound.requester,
                        project_id=bound.workspace, current_node_id="audience_proof", node_state={"entry": 3},
                        status="waiting", context=dict(bound.run.context))
    db.add(other)
    await db.flush()
    outcome = await receipts.consume_audience_receipt(db, other)
    assert (outcome.ok, outcome.result["code"]) == (False, "no_receipt")
    assert await state_of(db, receipt) == "recorded"


async def test_a_new_publication_card_after_the_record_refuses_the_consume(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, receipt.challenge_id)).status_code == 200
    payload = {**bound.decision.payload, "title": "Another redraft"}
    bound.decision.payload, bound.decision.payload_hash = payload, payload_hash(payload)
    bound.intent.card_hash = payload_hash(payload)
    await db.flush()
    outcome = await receipts.consume_audience_receipt(db, bound.run)
    assert (outcome.ok, outcome.result["code"]) == (False, "binding_mismatch")
    assert await state_of(db, receipt) == "revoked"


async def test_a_tampered_recorded_result_is_refused(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index, criteria=[*CRITERIA, {"id": "AC-9", "text": "Refunds", "tests": [], "manual_only": True}])
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, receipt.challenge_id)).status_code == 200
    await db.refresh(receipt)
    forged = [{**item, "passed": True} for item in receipt.assertion_results]
    await db.execute(update(DocumentationAudienceReceipt).where(DocumentationAudienceReceipt.id == receipt.id)
                     .values(assertion_results=forged))
    await db.flush()
    outcome = await receipts.consume_audience_receipt(db, bound.run)
    assert (outcome.ok, outcome.failure_class) == (False, "safety")
    assert await state_of(db, receipt) == "revoked"


# --- identical bytes at a new version, stale, revoked, expired ---------------------------------------------------


async def test_identical_bytes_at_a_new_page_version_refuse_the_consume(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, receipt.challenge_id)).status_code == 200
    # Someone saved version 2 with the same bytes: the sync keeps the revision and moves the item's marker.
    await db.execute(update(KnowledgeSourceSyncItem).where(KnowledgeSourceSyncItem.external_id == PAGE_ID)
                     .values(version_marker="2"))
    await db.flush()
    outcome = await receipts.consume_audience_receipt(db, bound.run)
    assert (outcome.ok, outcome.result["code"]) == (False, "binding_mismatch")
    assert await state_of(db, receipt) == "revoked"


async def test_a_receipt_of_an_earlier_pass_is_stale(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    bound.run.node_state = {"entry": 4}  # the node was entered again
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    response = await prove(client, bound.workspace, receipt.challenge_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "binding_mismatch"
    assert await state_of(db, receipt) == "revoked"
    outcome = await receipts.consume_audience_receipt(db, bound.run)
    assert (outcome.ok, outcome.result["code"]) == (False, "no_receipt")


async def test_a_superseded_challenge_is_revoked_and_never_recorded(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    first = await receipts.issue_audience_challenge(db, bound.run)
    assert (await receipts.issue_audience_challenge(db, bound.run)).id == first.id  # same pass: the same challenge
    bound.run.node_state = {"entry": 4}
    second = await receipts.issue_audience_challenge(db, bound.run)
    assert second.id != first.id and await state_of(db, first) == "revoked"
    assert first.revoke_reason == "superseded"
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    response = await prove(client, bound.workspace, first.challenge_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "state_refused"


async def test_an_expired_challenge_or_receipt_is_refused(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    past = utc_now() - dt.timedelta(minutes=1)
    await db.execute(update(DocumentationAudienceReceipt).where(DocumentationAudienceReceipt.id == receipt.id)
                     .values(issued_at=past - dt.timedelta(hours=1), expires_at=past))
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    response = await prove(client, bound.workspace, receipt.challenge_id)
    assert response.status_code == 410 and await state_of(db, receipt) == "expired"
    outcome = await receipts.consume_audience_receipt(db, bound.run)
    assert (outcome.ok, outcome.result["code"]) == (False, "expired")
    # A recorded receipt that expires before the consume is refused too.
    bound.run.node_state = {"entry": 5}
    fresh = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    assert (await prove(client, bound.workspace, fresh.challenge_id)).status_code == 200
    await db.execute(update(DocumentationAudienceReceipt).where(DocumentationAudienceReceipt.id == fresh.id)
                     .values(issued_at=past - dt.timedelta(hours=1), expires_at=past))
    await db.flush()
    late = await receipts.consume_audience_receipt(db, bound.run)
    assert (late.ok, late.result["code"]) == (False, "expired") and await state_of(db, fresh) == "expired"


async def test_p_losing_the_role_or_becoming_admin_refuses_the_consume(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    for change in ("lost_role", "became_admin"):
        bound = await bind_publication(db, runtime, evidence_index)
        receipt = await receipts.issue_audience_challenge(db, bound.run)
        await db.commit()
        as_user(await fetch_user(db, bound.principal))
        assert (await prove(client, bound.workspace, receipt.challenge_id)).status_code == 200
        if change == "lost_role":
            await db.execute(delete(UserProject).where(UserProject.user_id == bound.principal))
        else:
            await make_admin(db, bound.principal)
        await db.flush()
        outcome = await receipts.consume_audience_receipt(db, bound.run)
        assert (outcome.ok, outcome.result["code"]) == (False, "principal_refused"), change
        assert await state_of(db, receipt) == "revoked"


async def test_stopped_run_never_consumes_or_records_proof(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, receipt.challenge_id)).status_code == 200
    bound.run.status = 'stopped'
    await db.commit()
    consumed = await receipts.consume_audience_receipt(db, bound.run)
    assert not consumed.ok and consumed.result['code'] == 'state_refused'
    assert await state_of(db, receipt) == 'recorded'


async def test_newer_publication_change_invalidates_old_confirmed_proof(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, receipt.challenge_id)).status_code == 200
    db.add(WorkflowRunDecision(run_id=bound.run.id, node_id='confirm_publication', kind='confirmation',
        subject='publication', action='changed', payload=bound.decision.payload,
        payload_hash=bound.decision.payload_hash, decided_by=bound.requester))
    await db.commit()
    consumed = await receipts.consume_audience_receipt(db, bound.run)
    assert not consumed.ok and consumed.result['code'] == 'binding_mismatch'


async def test_deferred_done_rechecks_consumed_proofs_without_consuming_again(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    p = await receipts.issue_audience_challenge(db, bound.run)
    o = await receipts.issue_audience_challenge(db, bound.run, principal_role=audience_contract.ROLE_OUTSIDER)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, p.challenge_id)).status_code == 200
    as_user(await fetch_user(db, bound.outsider))
    assert (await prove(client, bound.workspace, o.challenge_id)).status_code == 200
    assert (await receipts.consume_audience_receipt(db, bound.run)).ok
    assert (await receipts.consume_audience_receipt(db, bound.run, principal_role=audience_contract.ROLE_OUTSIDER)).ok
    bound.run.current_node_id = 'acceptance_resolved'
    bound.run.node_state = {'entry': 9}
    await db.commit()
    assert (await receipts.validate_current_publication_proof(db, bound.run)).ok
    assert await state_of(db, p) == 'consumed' and await state_of(db, o) == 'consumed'
    await db.execute(delete(UserProject).where(UserProject.user_id == bound.principal))
    await db.commit()
    assert not (await receipts.validate_current_publication_proof(db, bound.run)).ok
