"""S1 personal proof action: real JWT principal, blind Inbox, ledger retrieval and graph wake.

All users/tokens/storage/database rows are isolated test fixtures. No real principal credential, provider,
acceptance database or external account is used. The existing deterministic object/index adapters model the source.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from app.models import FlowDefinition, FlowDefinitionVersion
from app.models.security.user import UserProject
from app.services.auth import create_access_token
from app.services.inbox.service import personal_inbox
from app.services.knowledge.runtime import set_evidence_runtime
from app.services.workflow_runs.documentation import audience_receipt as receipts
from app.services.workflow_runs.documentation import preflight, publish_prove_state, s1_graph
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user
from tests.phased_workflow_fixtures import publish_phased
from tests.s1_receipt_flow_support import SOURCE_KEY, TITLE, bind_publication

pytestmark = pytest.mark.asyncio
PREFIX = "/api/v1/workflow-runs/audience-receipts"


@pytest.fixture
def runtime_fixture():
    runtime, _store, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, evidence_index
    finally:
        set_evidence_runtime(None)


def headers(user_id):
    return {"Authorization": "Bearer " + create_access_token(user_id)}


async def ready(db, runtime_fixture, role="audience"):
    runtime, evidence_index = runtime_fixture
    bound = await bind_publication(db, runtime, evidence_index)
    # This definition tests the actual audience action -> engine continuation, not the larger S1 acceptance goal.
    definition = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "audience_proof", "type": "platform_action", "config": {
            "action": s1_graph.AUDIENCE_PROOF, "params": {"principal_role": role}}},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
        {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}},
    ], "edges": [
        {"id": "start", "source_node_id": "start", "target_node_id": "audience_proof"},
        {"id": "pass", "source_node_id": "audience_proof", "target_node_id": "done", "when": "succeeded"},
        {"id": "fail", "source_node_id": "audience_proof", "target_node_id": "blocked", "when": "failed"},
    ]}
    key = await publish_phased(db, definition)
    version = (await db.execute(select(FlowDefinitionVersion).join(FlowDefinition).where(
        FlowDefinition.key == key))).scalars().first()
    bound.run.flow_definition_version_id = version.id
    bound.run.workflow_key = key
    bound.run.waiting_kind = "audience_receipt"
    bound.run.title = "PRIVATE RUN TITLE"
    receipt = await receipts.issue_audience_challenge(db, bound.run, principal_role=role)
    bound.run.node_state = {**bound.run.node_state, "waiting": {
        "kind": "audience_receipt", **s1_graph._waiting_view(receipt, role)}}
    await db.commit()
    return bound, receipt


async def test_real_authenticated_principal_records_and_wakes_the_waiting_graph(client, db, runtime_fixture):
    bound, receipt = await ready(db, runtime_fixture)
    result = await client.post(f"{PREFIX}/{receipt.challenge_id}/record", headers=headers(bound.principal))
    assert result.status_code == 200, result.text
    await db.refresh(receipt)
    await db.refresh(bound.run)
    assert receipt.recorded_by == bound.principal and receipt.state == "consumed"
    assert bound.run.status == "completed" and bound.run.current_node_id == "done"
    assert result.json()["proof"]["outcome"] == "positive"


async def test_wrong_authenticated_actor_and_unknown_challenge_have_identical_generic_denial(
        client, db, runtime_fixture):
    bound, receipt = await ready(db, runtime_fixture)
    wrong = await client.post(f"{PREFIX}/{receipt.challenge_id}/record", headers=headers(bound.outsider))
    unknown = await client.post(f"{PREFIX}/unknown-fixture/record", headers=headers(bound.outsider))
    assert wrong.status_code == unknown.status_code == 404
    wrong_body, unknown_body = wrong.json(), unknown.json()
    wrong_body.pop("request_id", None)
    unknown_body.pop("request_id", None)
    assert wrong_body == unknown_body
    assert receipt.challenge_id not in json.dumps(wrong_body) and bound.run.id not in json.dumps(wrong_body)
    await db.refresh(receipt)
    assert receipt.state == "issued" and receipt.recorded_by is None


async def test_action_requires_authentication_and_does_not_take_an_actor_from_the_request_body(
        client, db, runtime_fixture):
    bound, receipt = await ready(db, runtime_fixture)
    unauthenticated = await client.post(f"{PREFIX}/{receipt.challenge_id}/record")
    assert unauthenticated.status_code == 401
    wrong = await client.post(f"{PREFIX}/{receipt.challenge_id}/record", headers=headers(bound.outsider),
                              json={"user_id": bound.principal, "workspace_id": bound.workspace})
    assert wrong.status_code == 404
    await db.refresh(receipt)
    assert receipt.state == "issued"


async def test_personal_inbox_is_blind_and_only_offers_the_owned_challenge(db, runtime_fixture):
    bound, receipt = await ready(db, runtime_fixture, role="outsider")
    outsider = await fetch_user(db, bound.outsider)
    inbox = await personal_inbox(db, outsider)
    rows = [item for item in inbox["waiting"] if item["kind"] == "workflow_run_audience_receipt"]
    assert len(rows) == 1 and rows[0]["id"] == receipt.challenge_id
    assert rows[0]["proof_action"] == {"challenge_id": receipt.challenge_id}
    encoded = json.dumps(rows)
    for protected in (bound.run.id, bound.workspace, TITLE, SOURCE_KEY, "PRIVATE RUN TITLE"):
        assert protected not in encoded
    assert "page_id" not in encoded and "query_set" not in encoded
    unrelated = await publish_prove_state.inbox_items(db, bound.principal)
    assert not any(item["kind"] == "workflow_run_audience_receipt" for item in unrelated)


async def test_expired_challenge_is_refused_before_retrieval(client, db, runtime_fixture, monkeypatch):
    bound, receipt = await ready(db, runtime_fixture)
    receipt.issued_at = utc_now() - timedelta(minutes=2)
    receipt.expires_at = utc_now() - timedelta(seconds=1)
    await db.commit()
    from app.services.knowledge.retrieval import evidence
    async def never(*args, **kwargs):
        raise AssertionError("expired challenge must not read Knowledge")
    monkeypatch.setattr(evidence, "retrieve_workspace_evidence", never)
    result = await client.post(f"{PREFIX}/{receipt.challenge_id}/record", headers=headers(bound.principal))
    assert result.status_code == 410
    await db.refresh(receipt)
    assert receipt.state == "expired" and receipt.recorded_by is None


async def test_current_membership_is_rechecked_before_retrieval(client, db, runtime_fixture, monkeypatch):
    bound, receipt = await ready(db, runtime_fixture)
    await db.execute(delete(UserProject).where(UserProject.user_id == bound.principal,
                                               UserProject.project_id == bound.workspace))
    await db.commit()
    from app.services.knowledge.retrieval import evidence
    async def never(*args, **kwargs):
        raise AssertionError("revoked actor must not read Knowledge")
    monkeypatch.setattr(evidence, "retrieve_workspace_evidence", never)
    result = await client.post(f"{PREFIX}/{receipt.challenge_id}/record", headers=headers(bound.principal))
    assert result.status_code == 409
    await db.refresh(receipt)
    assert receipt.state == "revoked" and receipt.recorded_by is None


async def test_outsider_action_response_keeps_metadata_blind_and_records_negative_as_real_user(
        client, db, runtime_fixture):
    bound, receipt = await ready(db, runtime_fixture, role="outsider")
    result = await client.post(f"{PREFIX}/{receipt.challenge_id}/record", headers=headers(bound.outsider))
    assert result.status_code == 200, result.text
    assert set(result.json()["proof"]) == {"challenge_id", "state", "principal_role", "outcome"}
    assert result.json()["proof"]["outcome"] == "negative"
    await db.refresh(receipt)
    assert receipt.recorded_by == bound.outsider and receipt.state == "consumed"
    assert bound.run.id not in result.text and SOURCE_KEY not in result.text and TITLE not in result.text


async def test_canonical_settings_key_and_waiting_challenge_coordinates_align(db, runtime_fixture):
    bound, receipt = await ready(db, runtime_fixture)
    from app.models import Project
    config = (await db.get(Project, bound.workspace)).config
    graph_settings = preflight.audience_settings(config)
    assert graph_settings.principal_user_id == bound.principal
    assert graph_settings.outsider_user_id == bound.outsider
    waiting = bound.run.node_state["waiting"]
    assert waiting["challenge_id"] == receipt.challenge_id
    assert waiting["principal_role"] == "audience"
    assert waiting["expected_principal_id"] == bound.principal
