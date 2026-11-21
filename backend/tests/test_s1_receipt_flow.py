"""Audience receipts: server-owned challenge, P's real retrieval, single consume.

Everything runs through the product's code: the Workspace Knowledge ledger and projection (in-memory object
store and Evidence index doubles), the real ``POST /knowledge/search`` route with ``proof_request`` as the authenticated
caller, and the receipt service. The published page is bound like the publish and the provenance steps leave it:
a sent-confirmed write intent bound to the confirmed (b) decision, a sync item ingested at the published
version from the published instance, and the pinned provenance on the run. No network.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import DocumentationAudienceReceipt, Project
from app.services.workflow_runs.documentation import audience_contract, audience_principals
from app.services.workflow_runs.documentation import audience_receipt as receipts
from app.services.workflow_runs.pause import payload_hash
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.s1_receipt_flow_support import (  # noqa: F401
    BASE,
    CRITERIA,
    as_user,
    bind_publication,
    evidence_runtime,
    make_admin,
    prove,
    standalone_receipt_service,
    state_of,
)

pytestmark = pytest.mark.asyncio


# --- configuration (O1) -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("audience", [{}, {"semantics": "everyone", "principal_user_id": "x"},
                                      {"semantics": "workspace_readers", "principal_user_id": ""}])
async def test_without_a_configured_principal_the_challenge_needs_configuration(db, evidence_runtime, audience):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index, audience=audience or {"unset": True})
    with pytest.raises(audience_contract.AudienceProofError) as refused:
        await receipts.issue_audience_challenge(db, bound.run)
    assert (refused.value.code, refused.value.failure_class) == ("needs_configuration", "needs_configuration")
    outcome = await receipts.issue_audience_challenge_action(db, bound.run, {})
    assert (outcome.ok, outcome.failure_class) == (False, "needs_configuration")
    assert await audience_principals.audience_configuration_refusal(db, bound.run)
    assert (await db.execute(select(DocumentationAudienceReceipt))).scalars().all() == []


async def test_source_restricted_semantics_depend_on_the_enforce_switch_and_never_turn_it_on(db, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index, semantics=audience_contract.SEMANTICS_SOURCE)
    project = await db.get(Project, bound.workspace)
    project.config = {key: value for key, value in project.config.items() if key != "knowledge_source_acl"}
    await db.flush()
    with pytest.raises(audience_contract.AudienceProofError) as refused:
        await receipts.issue_audience_challenge(db, bound.run)
    assert refused.value.failure_class == "needs_configuration"
    assert "knowledge_source_acl" not in (await db.get(Project, bound.workspace)).config


async def test_admin_is_never_accepted_as_the_audience(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    # A global admin as the configured P: refused at issue (and by the preflight).
    admin = await seed_member(db, workspace_id=bound.workspace, role="member")
    await make_admin(db, admin)
    project = await db.get(Project, bound.workspace)
    proof = dict(project.config["feature_documentation"]["audience_proof"])

    async def approved_audience():
        # Admission test: the fixture approves this audience; drift has separate counterprobes.
        bound.decision.payload = {**bound.decision.payload, "audience": {
            **project.config["feature_documentation"]["audience_proof"], "workspace_id": bound.workspace}}
        bound.decision.payload_hash = payload_hash(bound.decision.payload)
        bound.intent.card_hash = bound.decision.payload_hash
        await db.flush()

    for configured in (admin, bound.requester):
        project.config = {**project.config, "feature_documentation": {
            **project.config["feature_documentation"], "audience_proof": {**proof, "principal_user_id": configured}}}
        await approved_audience()
        with pytest.raises(audience_contract.AudienceProofError) as refused:
            await receipts.issue_audience_challenge(db, bound.run)
        assert refused.value.code == "principal_refused"
        assert await audience_principals.audience_configuration_refusal(db, bound.run)
    # A Workspace admin is refused as well (an admin role is not the audience).
    owner = await seed_member(db, workspace_id=bound.workspace, role="admin")
    project.config = {**project.config, "feature_documentation": {
        **project.config["feature_documentation"], "audience_proof": {**proof, "principal_user_id": owner}}}
    await approved_audience()
    with pytest.raises(audience_contract.AudienceProofError):
        await receipts.issue_audience_challenge(db, bound.run)
    # With the real P configured, an admin presenting P's challenge is not P: same 404 as an unknown challenge.
    project.config = {**project.config, "feature_documentation": {
        **project.config["feature_documentation"], "audience_proof": proof}}
    await approved_audience()
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, admin))
    response = await prove(client, bound.workspace, receipt.challenge_id)
    unknown = await prove(client, bound.workspace, uuid.uuid4().hex)
    assert response.status_code == unknown.status_code == 404
    assert response.json()["detail"] == unknown.json()["detail"]
    assert await state_of(db, receipt) == "issued"


# --- the positive receipt ---------------------------------------------------------------------------------------


async def test_p_runs_the_servers_query_set_and_the_run_consumes_the_receipt_once(db, client, as_user,  # noqa: F811
                                                                                 evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    bound = await bind_publication(db, runtime, evidence_index)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    assert receipt.expected_principal_id == bound.principal and receipt.page_version == 1
    assert [item["id"] for item in receipt.query_set] == [
        "section:what", "section:why", "section:how-to-use", "criterion:AC-1", "criterion:AC-2"]
    assert receipt.publication_card_hash == bound.decision.payload_hash == bound.intent.card_hash
    await db.commit()
    principal = await fetch_user(db, bound.principal)
    as_user(principal)
    # The caller's own query fields are not used: a weaker query and a narrowing product scope change nothing.
    response = await prove(client, bound.workspace, receipt.challenge_id, query_text="nothing",
                           run_id=bound.run.id, publication_card_hash=receipt.publication_card_hash)
    assert response.status_code == 200, response.text
    recorded = response.json()["proof"]
    assert (recorded["state"], recorded["outcome"], recorded["query_source"]) == ("recorded", "positive",
                                                                                   "server_challenge")
    assert all(item["passed"] for item in recorded["assertions"]) and recorded["bound_hits"] >= 5
    assert await state_of(db, receipt) == "recorded" and receipt.recorded_by == bound.principal

    consumed = await receipts.consume_audience_receipt(db, bound.run)
    assert consumed.ok, consumed.reason
    # The page version is the intent's 1; the hits' subject version 9.9 is never read as the page version.
    assert consumed.result["page_version"] == 1
    search = await client.post(f"{BASE}/{bound.workspace}/knowledge/search",
                               json={"query_text": "invoice totals", "mode": "lexical"})
    assert {hit["version"] for hit in search.json()["evidence"]} == {"9.9"}
    assert bound.run.context["documentation"]["audience_proof"]["audience"]["revision_id"] == bound.binding.revision_id
    assert await state_of(db, receipt) == "consumed" and receipt.consumed_by_run_id == bound.run.id

    # Replayed: neither a second consume nor a second record is accepted.
    again = await receipts.consume_audience_receipt(db, bound.run)
    assert (again.ok, again.result["code"]) == (False, "replayed")
    replay = await prove(client, bound.workspace, receipt.challenge_id)
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == "state_refused"


async def test_a_missing_assertion_never_proves_the_audience(db, client, as_user, evidence_runtime):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    criteria = [*CRITERIA, {"id": "AC-9", "text": "Refunds reverse the fee within one day", "tests": [],
                            "manual_only": True}]
    bound = await bind_publication(db, runtime, evidence_index, criteria=criteria)
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    await db.commit()
    as_user(await fetch_user(db, bound.principal))
    response = await prove(client, bound.workspace, receipt.challenge_id)
    assert response.json()["proof"]["outcome"] == "positive"  # the page is there ...
    assert {item["id"]: item["passed"] for item in response.json()["proof"]["assertions"]}["criterion:AC-9"] is False
    outcome = await receipts.consume_audience_receipt(db, bound.run)
    assert (outcome.ok, outcome.failure_class, outcome.result["code"]) == (False, "audience_unproven",
                                                                           "assertions_failed")
    assert await state_of(db, receipt) == "revoked"  # ... but not every assertion: never proof
