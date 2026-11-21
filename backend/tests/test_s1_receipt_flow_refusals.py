"""Outsider negatives and refused proof requests, coordinates, query sets and stored credentials for audience receipts."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.models import DocumentationAudienceReceipt, User
from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
from app.models.security.user import UserProject
from app.services.workflow_runs.documentation import audience_contract
from app.services.workflow_runs.documentation import audience_receipt as receipts
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.s1_receipt_flow_support import (  # noqa: F401
    PAGE_ID,
    as_user,
    bind_publication,
    evidence_runtime,
    prove,
    standalone_receipt_service,
    state_of,
)

pytestmark = pytest.mark.asyncio


# --- the outsider-negative receipt -------------------------------------------------------------------------------


async def test_the_workspace_outsider_negative_is_recorded_and_consumed_beside_ps_receipt(db, client, as_user,  # noqa: F811
                                                                                         evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    positive = await receipts.issue_audience_challenge(db, bound.run)
    negative = await receipts.issue_audience_challenge(db, bound.run, principal_role=audience_contract.ROLE_OUTSIDER)
    assert negative.pass_key.endswith("@outsider") and positive.pass_key.endswith("@audience")
    await db.commit()
    as_user(await fetch_user(db, bound.outsider))
    response = await prove(client, bound.workspace, negative.challenge_id)
    assert response.status_code == 200 and response.json()["proof"]["outcome"] == "negative"
    assert "assertions" not in response.json()["proof"]
    assert "page_id" not in response.json()["proof"]
    # P cannot record the outsider's challenge, and the outsider cannot record P's.
    assert (await prove(client, bound.workspace, positive.challenge_id)).status_code == 404
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, positive.challenge_id)).status_code == 200
    outsider = await receipts.consume_audience_receipt(db, bound.run, principal_role=audience_contract.ROLE_OUTSIDER)
    audience = await receipts.consume_audience_receipt(db, bound.run)
    assert outsider.ok and audience.ok, (outsider.reason, audience.reason)
    assert outsider.result["semantics"] == "workspace_readers"  # Workspace proof only, not source-ACL proof
    proofs = bound.run.context["documentation"]["audience_proof"]
    assert (proofs["outsider"]["outcome"], proofs["audience"]["outcome"]) == ("negative", "positive")


async def test_the_source_restricted_outsider_reads_the_workspace_but_not_the_page(db, client, as_user,  # noqa: F811
                                                                                  evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index, semantics=audience_contract.SEMANTICS_SOURCE)
    positive = await receipts.issue_audience_challenge(db, bound.run)
    negative = await receipts.issue_audience_challenge(db, bound.run, principal_role=audience_contract.ROLE_OUTSIDER)
    assert positive.issue_checks["principal_admitted"] is True and negative.issue_checks["principal_admitted"] is False
    await db.commit()
    as_user(await fetch_user(db, bound.outsider))
    response = await prove(client, bound.workspace, negative.challenge_id)
    assert response.status_code == 200, response.text
    assert response.json()["proof"]["outcome"] == "negative"
    assert "assertions" not in response.json()["proof"]
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, bound.workspace, positive.challenge_id)).json()["proof"]["outcome"] == "positive"
    assert (await receipts.consume_audience_receipt(db, bound.run, principal_role=audience_contract.ROLE_OUTSIDER)).ok
    assert (await receipts.consume_audience_receipt(db, bound.run)).ok


async def test_an_outsider_who_retrieves_the_page_is_never_a_negative(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    negative = await receipts.issue_audience_challenge(db, bound.run, principal_role=audience_contract.ROLE_OUTSIDER)
    await db.commit()
    # The outsider gains Workspace access after the challenge: the record re-check revokes it.
    db.add(UserProject(user_id=bound.outsider, project_id=bound.workspace, role="member"))
    await db.commit()
    as_user(await fetch_user(db, bound.outsider))
    response = await prove(client, bound.workspace, negative.challenge_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "principal_refused"
    assert await state_of(db, negative) == "revoked"


# --- foreign or substituted input -------------------------------------------------------------------------------


@pytest.mark.parametrize("extra", [{"query_set": [{"id": "x", "query": "fee"}]},
                                   {"hits": [{"evidence_key": "k"}]}, {"outcome": "positive"},
                                   {"expected_principal_id": "someone"}])
async def test_a_proof_request_carrying_queries_hits_or_results_is_refused(db, client, as_user, evidence_runtime,  # noqa: F811
                                                                          extra):
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    response = await prove(client, bound.workspace, receipt.challenge_id, **extra)
    assert response.status_code == 422
    assert await state_of(db, receipt) == "issued"


@pytest.mark.parametrize("coordinates", [{"run_id": "11111111-1111-1111-1111-111111111111"},
                                         {"pass_key": "audience_proof#1@audience"},
                                         {"publication_card_hash": "sha256:" + "0" * 64}])
async def test_coordinates_of_another_run_pass_or_card_are_refused(db, client, as_user, evidence_runtime,  # noqa: F811
                                                                  coordinates):
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    response = await prove(client, bound.workspace, receipt.challenge_id, **coordinates)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "binding_mismatch"
    assert await state_of(db, receipt) == "issued"


async def test_another_caller_or_workspace_cannot_record_ps_challenge(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    other_member = await seed_member(db, workspace_id=bound.workspace, role="member")
    await db.commit()
    for caller in (bound.requester, other_member):
        as_user(await fetch_user(db, caller))
        assert (await prove(client, bound.workspace, receipt.challenge_id)).status_code == 404
    as_user(await fetch_user(db, bound.principal))
    assert (await prove(client, await seed_workspace(db), receipt.challenge_id)).status_code == 404
    assert await state_of(db, receipt) == "issued"


async def test_a_weakened_stored_query_set_is_refused_and_revoked(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.execute(update(DocumentationAudienceReceipt).where(DocumentationAudienceReceipt.id == receipt.id)
                     .values(query_set=[{"id": "section:what", "kind": "section", "query": "fee", "expect": []}]))
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    response = await prove(client, bound.workspace, receipt.challenge_id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "binding_mismatch"
    assert await state_of(db, receipt) == "revoked"


async def test_no_token_or_credential_is_ever_stored(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    principal = await fetch_user(db, bound.principal)
    principal.password_hash = "s1-unique-fake-password-hash-not-in-receipts"
    await db.commit()
    as_user(principal)
    response = await prove(client, bound.workspace, receipt.challenge_id)
    assert response.status_code == 200
    await db.refresh(receipt)
    stored = str({column.name: getattr(receipt, column.name) for column in DocumentationAudienceReceipt.__table__.c})
    for secret in ("Bearer", "password", "token", principal.password_hash):
        assert secret not in stored
    assert isinstance(await db.get(User, bound.principal), User)


async def test_outsider_response_has_no_protected_assertions(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run, principal_role=audience_contract.ROLE_OUTSIDER)
    await db.commit()
    as_user(await fetch_user(db, bound.outsider))
    response = await prove(client, bound.workspace, receipt.challenge_id)
    assert response.status_code == 200
    assert 'AC-1' not in response.text and 'section:what' not in response.text
    await db.execute(update(KnowledgeSourceSyncItem).where(KnowledgeSourceSyncItem.external_id == PAGE_ID)
                     .values(version_marker='2'))
    await db.commit()
    response = await prove(client, bound.workspace, receipt.challenge_id)
    assert response.status_code == 409
    assert PAGE_ID not in response.text and 'version 2' not in response.text
