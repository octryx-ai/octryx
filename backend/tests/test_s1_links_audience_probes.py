"""Approved list-item probes, same-current-hit conjunction and supported fresh challenge retry."""
from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import select

from app.models import DocumentationAudienceReceipt, FlowDefinition
from app.services.workflow_runs.documentation import audience_publication, audience_query_set, receipt_record
from app.services.workflow_runs.documentation import audience_receipt as receipts
from app.services.workflow_runs.documentation.audience_contract import AudienceProofError
from app.services.workflow_runs.documentation.audience_query_set import derive_query_set
from tests import s1_receipt_flow_support as support
from tests.knowledge_evidence_seed_support import fetch_user
from tests.s1_receipt_flow_support import evidence_runtime  # noqa: F401

LINKS = {"ticket": {"key": "BRD-18", "url": "https://jira.example/browse/BRD-18"},
         "pull_request": {"id": "6", "url": "https://code.example/pr/6"}}
ACTUAL = "Links\n\n- Ticket: BRD-18\n\nTicket: BRD-18\n\n- Pull request: #6\n\nPull request: #6\n\nNotes"
ITEMS = "<h2>Links</h2><ul><li>Ticket: <a href='https://jira.example'>BRD-18</a></li>" \
        "<li>Pull request: <a href='https://code.example'>#6</a></li></ul>"


def links_query(body=ITEMS):
    return next(item for item in derive_query_set({"body": body}) if item["id"] == "section:links")


def test_actual_duplicate_bullet_projection_and_normal_rendering_require_both_full_labels():
    query = links_query()
    assert query["query"] == "Ticket: BRD-18 Pull request: #6"
    assert query["expect"] == ["ticket: brd-18", "pull request: #6"]
    for text in (ACTUAL, "Ticket: BRD-18 Pull request: #6"):
        assert all(probe in audience_query_set.normalized(text) for probe in query["expect"])
    for text in ("Ticket: BRD-18", "Pull request: #6", "Ticket: BRD-12 Pull request: #3"):
        assert not all(probe in audience_query_set.normalized(text) for probe in query["expect"])
    assert not any(all(probe in audience_query_set.normalized(hit) for probe in query["expect"])
                   for hit in ["Ticket: BRD-18", "Pull request: #6"])


def test_paragraph_criterion_and_valid_empty_generated_links_keep_existing_behavior():
    body = "<h2>What</h2><p>One two three four five six seven eight nine.</p><h2>Links</h2><p>Ticket: BRD-18</p>"
    queries = derive_query_set({"body": body, "acceptance_criteria": [{"id": "AC1", "text": "Existing behavior"}]})
    assert queries[0]["expect"] == ["one two three four five six seven eight"]
    assert queries[1]["expect"] == ["ticket: brd-18"]
    assert queries[2]["expect"] == ["ac1", "existing behavior"]
    assert derive_query_set({"body": "<h2>What</h2><p>Observed behavior.</p><h2>Links</h2><ul></ul>"}) == [
        {"id": "section:what", "kind": "section", "heading": "What", "query": "Observed behavior.",
         "expect": ["observed behavior."]}]


@pytest.mark.parametrize("html", [
    "<ul><li>Ticket: BRD-18</ul>", "<ul><li>Ticket: BRD-18", "<li>Ticket: BRD-18</li>",
    "<ul><li><a href='x'>Ticket: BRD-18</li></ul>",
    "<ul><li>Ticket<ul><li>BRD-18</li></ul></li></ul>",
    "<ul><li><a href='https://jira.example/BRD-18'> </a></li></ul>",
    "<ul><li>" + "x" * 301 + "</li></ul>",
    "<ul>" + "<li>short</li>" * 11 + "</ul>",
    "<ul><li>Ticket: BRD-18</li>" + "<li></li>" * 10 + "</ul>",
    "<ul><li>" + "a" * 160 + "</li><li>" + "b" * 160 + "</li></ul>",
    "Extra approved text<ul><li>Ticket: BRD-18</li></ul>",
    "<ul><li>Ticket: BRD-18</li></ul><p>Extra required approved content</p>",
])
def test_malformed_oversized_or_unaccounted_links_fail_closed(html):
    with pytest.raises(AudienceProofError, match="Links list"):
        derive_query_set({"body": "<h2>Links</h2>" + html})


def test_href_never_becomes_a_visible_text_probe():
    query = links_query("<h2>Links</h2><ul><li><a href='https://jira.example/BRD-18'>Ticket reference</a></li></ul>")
    assert query["expect"] == ["ticket reference"]
    assert "BRD-18" not in query["query"]


async def bound_links(db, evidence_runtime, monkeypatch, text):  # noqa: F811
    runtime, _s3, evidence_index = evidence_runtime
    monkeypatch.setattr(support, "NO_LINKS", LINKS)
    monkeypatch.setattr(support, "TEXT", support.TEXT + b"\n\n" + text.encode())
    bound = await support.bind_publication(db, runtime, evidence_index)
    return bound, runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["actual", "missing_ticket", "missing_pr", "separate_hits", "foreign_source", "acl_revoked", "version"])
async def test_real_receipt_uses_all_labels_within_one_bound_hit(db, evidence_runtime, monkeypatch, variant):  # noqa: F811
    text = "Links\n- Ticket: BRD-18\nTicket: BRD-18\n- Pull request: #6\nPull request: #6"
    if variant == "missing_ticket":
        text = "Links\nPull request: #6"
    elif variant == "missing_pr":
        text = "Links\nTicket: BRD-18"
    elif variant == "separate_hits":
        text = "Links\nTicket: BRD-18\n\nPull request: #6"
    if variant == "foreign_source":
        text = "Links\nThe approved labels are absent here."
    bound, runtime = await bound_links(db, evidence_runtime, monkeypatch, text)
    if variant == "foreign_source":
        from app.services.knowledge.access.authorization import authorize_workspace
        from app.services.knowledge.ingestion.text_ingest import ingest_text_source
        from app.services.knowledge.projection.projector import EvidenceProjector

        authorized = await authorize_workspace(db, current_user=await fetch_user(db, bound.requester),
                                                workspace_id=bound.workspace, require_author=True)
        await ingest_text_source(db, runtime=runtime, authorized=authorized, source_key="confluence.docs.9999",
            display_title="Other page", declared_media_type="text/plain", data=ACTUAL.encode(),
            created_by=bound.requester, source_url="https://docs.example.test/wiki/pages/9999")
        while await EvidenceProjector(runtime).project_once(db, worker_id="links-other-page",
                                                           project_id=bound.workspace) is not None:
            pass
    receipt = await receipts.issue_audience_challenge(db, bound.run)
    assert next(q for q in receipt.query_set if q["id"] == "section:links")["expect"] == [
        "ticket: brd-18", "pull request: #6"]
    await db.commit()
    if variant == "acl_revoked":
        from app.services.knowledge.access.source_acl import restrict_source
        await restrict_source(db, project_id=bound.workspace, source_key=support.SOURCE_KEY, restriction="restricted")
        await db.commit()
    elif variant == "version":
        from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
        row = (await db.execute(select(KnowledgeSourceSyncItem).where(
            KnowledgeSourceSyncItem.connector_id == bound.connector.id))).scalar_one()
        row.version_marker = "2"
        await db.commit()
    actor = await fetch_user(db, bound.principal)
    if variant in {"acl_revoked", "version"}:
        with pytest.raises(AudienceProofError):
            await receipt_record.record_audience_receipt(db, current_user=actor, workspace_id=bound.workspace,
                proof_request={"challenge_id": receipt.challenge_id}, runtime=runtime)
        assert receipt.consumed_at is None
        return
    result = await receipt_record.record_audience_receipt(db, current_user=actor, workspace_id=bound.workspace,
        proof_request={"challenge_id": receipt.challenge_id}, runtime=runtime)
    assertion = next(q for q in result["assertions"] if q["id"] == "section:links")
    assert assertion["passed"] is (variant == "actual")
    outcome = await receipts.consume_audience_receipt(db, bound.run)
    assert outcome.ok is (variant == "actual")
    if variant != "actual":
        assert receipt.consumed_at is None


@pytest.mark.asyncio
async def test_supported_retry_reissues_corrected_query_digest_without_republish(db, evidence_runtime, monkeypatch):  # noqa: F811
    from app.services.workflow_runs.actions import available_actions, perform_action
    from app.services.workflow_runs.documentation.s1_graph import check_audience_receipt
    from tests.phased_workflow_fixtures import publish_phased

    text = "Links\n- Ticket: BRD-18\nTicket: BRD-18\n- Pull request: #6\nPull request: #6"
    bound, runtime = await bound_links(db, evidence_runtime, monkeypatch, text)
    graph = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "audience_proof", "type": "platform_action", "config": {
            "action": "documentation.audience_proof", "params": {"principal_role": "audience"}}},
        {"id": "proof_failed", "type": "pause", "config": {"reason": "action_failed"}},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
        {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}], "edges": [
        {"id": "1", "source": "start", "target": "audience_proof"},
        {"id": "2", "source": "audience_proof", "target": "done", "when": "succeeded"},
        {"id": "3", "source": "audience_proof", "target": "proof_failed", "when": "failed"},
        {"id": "4", "source": "proof_failed", "target": "blocked"}]}
    key = await publish_phased(db, graph, key=f"receipt-retry-{uuid.uuid4().hex}")
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    bound.run.flow_definition_version_id = flow.current_version_id
    bound.run.waiting_kind = "audience_receipt"
    bound.run.node_state = {"entry": 3, "waiting": {"principal_role": "audience"}}
    approved_card, approved_body = bound.decision.payload_hash, bound.decision.payload["body"]
    current_derive = audience_publication.derive_query_set

    def old_flattened(payload):
        result = copy.deepcopy(current_derive(payload))
        for assertion in result:
            if assertion["id"] == "section:links":
                assertion["expect"] = [audience_query_set.normalized(assertion["query"])]
        return result

    with monkeypatch.context() as old_code:
        old_code.setattr(audience_publication, "derive_query_set", old_flattened)
        old = await receipts.issue_audience_challenge(db, bound.run)
        await db.commit()
        result = await receipt_record.record_audience_receipt(db, current_user=await fetch_user(db, bound.principal),
            workspace_id=bound.workspace, proof_request={"challenge_id": old.challenge_id}, runtime=runtime)
        assert next(a for a in result["assertions"] if a["id"] == "section:links")["passed"] is False
        assert await check_audience_receipt(db, bound.run, actor_id=bound.requester) == "failed"
        await db.commit()
    assert bound.run.status == "paused" and bound.run.pause_reason == "audience_unproven"
    requester = await fetch_user(db, bound.requester)
    assert "retry_action" in {a["key"] for a in await available_actions(db, bound.run, access="write", user=requester)}
    old_digest, old_pass = old.query_set_digest, old.pass_key
    await perform_action(db, bound.run, user=requester, body={"action": "retry_action"})
    await db.commit()
    fresh = (await db.execute(select(DocumentationAudienceReceipt).where(
        DocumentationAudienceReceipt.run_id == bound.run.id, DocumentationAudienceReceipt.state == "issued"))).scalar_one()
    assert fresh.id != old.id and fresh.challenge_id != old.challenge_id and fresh.pass_key != old_pass
    assert fresh.query_set_digest != old_digest
    assert next(a for a in fresh.query_set if a["id"] == "section:links")["expect"] == [
        "ticket: brd-18", "pull request: #6"]
    await db.refresh(old)
    assert old.state == "revoked" and old.consumed_at is None
    assert bound.decision.payload_hash == approved_card and bound.decision.payload["body"] == approved_body
    assert fresh.publication_card_hash == approved_card and fresh.page_version == old.page_version == 1
    assert fresh.revision_id == old.revision_id and bound.intent.state == "sent_confirmed"
    assert bound.run.status == "waiting" and bound.run.waiting_kind == "audience_receipt"
    await receipt_record.record_audience_receipt(db, current_user=await fetch_user(db, bound.principal),
        workspace_id=bound.workspace, proof_request={"challenge_id": fresh.challenge_id}, runtime=runtime)
    assert await check_audience_receipt(db, bound.run, actor_id=bound.requester) == "succeeded"
    await db.commit()
    assert bound.run.status == "completed" and bound.run.outcome == "done"
