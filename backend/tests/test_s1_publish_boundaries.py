"""Real publish services, test DB and transport stub: no provider network or privileged shortcuts."""
from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project, WorkflowRunDecision
from app.services.approval import resolve_approval_request
from app.services.workflow_runs.documentation import publication_v2 as publication
from app.services.workflow_runs.documentation.confluence_v2 import CloudV2Client
from app.services.workflow_runs.documentation.confluence_v2_storage import canonical_digest
from app.services.workflow_runs.documentation.write_intent import (
    PublicationIntentError,
    approve_publication_intent,
    publication_body_hash,
)
from app.services.workflow_runs.pause import payload_hash
from tests.s1_publish_cloud_support import API, PARENT, SITE, FakeCloudV2, answer, apply_then, read_timeout
from tests.s1_publish_run_support import Crash, crashed, publish, published_ready

pytestmark = pytest.mark.asyncio


async def project_config(db, run, **values):
    row = await db.get(Project, run.project_id)
    row.config = {**row.config, **values}
    await db.commit()


async def test_real_registry_refusal_and_approval_hold_do_not_claim_or_send(db):
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    await project_config(db, run, tool_policy={"denylist": ["create_confluence_page"]})
    before = len(fake.requests)
    denied = await publish(db, run, fake)
    assert not denied.ok and denied.failure_class == "permission"
    await db.refresh(intent)
    assert intent.state == "approved" and intent.claimed_by is None
    assert len(fake.requests) == before and not fake.writes
    await project_config(db, run, tool_policy={"allowlist": ["get_confluence_page", "create_confluence_page"]},
                         approval_policy={"require_for_tools": ["create_confluence_page"]})
    held = await publish(db, run, fake, entry=2)
    assert held.state == "approval_pending" and held.approval_id
    await db.refresh(intent)
    assert intent.state == "approved" and len(fake.requests) == before and not fake.writes


async def test_real_approval_is_bound_to_full_exact_parameters_then_consumed_once(db):
    from app.services.workflow_runs.documentation.confluence_v2 import governed_v2_check
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    await project_config(db, run, approval_policy={"require_for_tools": ["create_confluence_page"]})
    decision = await db.get(WorkflowRunDecision, intent.decision_id)
    body = decision.payload["body"]
    args = dict(instance=intent.instance, connection_id=intent.connection_id, space_key=intent.space_key,
                parent_id=intent.parent_id, title=intent.title, body=body)
    held = await governed_v2_check(db, run, **args)
    assert held.state == "approval_pending"
    await resolve_approval_request(db, approval_id=held.approval_id, resolved_by=run.requested_by, status="approved")
    drift = await governed_v2_check(db, run, **{**args, "body": body + "<p>not approved</p>"})
    assert drift.state == "approval_pending"
    assert await governed_v2_check(db, run, **args) is None
    assert (await governed_v2_check(db, run, **args)).state == "approval_pending"
    assert not fake.writes and intent.state == "approved"


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503])
async def test_applied_uncertain_http_answer_reconciles_without_second_post(db, status):
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    fake.faults["POST"] = answer(status, apply=True)
    first = await publish(db, run, fake)
    assert first.ok and first.result["status"] == "reconciled"
    second = await publish(db, run, fake, entry=2)
    assert second.ok and len(fake.writes) == 1
    assert len(fake.children(PARENT)) == 1


@pytest.mark.parametrize("point", ["before_send", "after_applied", "before_pending_record"])
async def test_process_crash_is_may_have_sent_and_never_resends(db, monkeypatch, point):
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    if point == "before_send":
        async def die(_intent):
            raise Crash()
        monkeypatch.setattr(publication, "_before_send", die)
    elif point == "after_applied":
        fake.faults["POST"] = apply_then(Crash())
    else:
        fake.faults["POST"] = apply_then(read_timeout())
        async def die(*_a, **_kw):
            raise Crash()
        monkeypatch.setattr("app.services.workflow_runs.documentation.write_intent.mark_pending_reconcile", die)
    await crashed(db, publish(db, run, fake, worker="original"))
    monkeypatch.undo()
    await db.refresh(run)
    await db.refresh(intent)
    assert intent.state == "send_started"
    writes = len(fake.writes)
    recovered = await publish(db, run, fake, entry=2, worker="original", reconcile=True)
    assert recovered.ok == (point != "before_send")
    assert len(fake.writes) == writes
    assert len(fake.children(PARENT)) == (0 if point == "before_send" else 1)


@pytest.mark.parametrize("field,value", [("instance", "https://another.atlassian.net/wiki"),
    ("connection_id", "another"), ("space_id", "999"), ("parent_id", "888"), ("operation_id", "other"),
    ("expected_version", 2), ("expected_version", True), ("base_version", 8), ("workspace_id", "different-workspace")])
async def test_confirmation_target_substitution_is_refused_before_i_o(db, field, value):
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    decision = await db.get(WorkflowRunDecision, intent.decision_id)
    decision.payload = {**decision.payload, "target": {**decision.payload["target"], field: value}}
    decision.payload_hash = payload_hash(decision.payload)
    await db.flush()
    before = len(fake.requests)
    with pytest.raises(PublicationIntentError, match="confirmed target"):
        await approve_publication_intent(db, run, decision_id=decision.id, card_hash=decision.payload_hash,
                                         output_hash=intent.output_hash, body_hash=intent.body_hash)
    assert len(fake.requests) == before and not fake.writes


@pytest.mark.parametrize("approved,stored", [("<pre>a  b</pre>", "<pre>a b</pre>"),
    ("<p>one  two</p>", "<p>one two</p>"), ("<code>line1\nline2</code>", "<code>line1 line2</code>"),
    ("<p>&lt;strong&gt;x&lt;/strong&gt;</p>", "<p><strong>x</strong></p>")])
async def test_full_content_proof_preserves_text_semantics(db, approved, stored):
    assert canonical_digest(approved) != canonical_digest(stored)
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    fake.store = lambda body: body.replace("Shows the totals.", "Shows  the totals.")
    result = await publish(db, run, fake)
    assert not result.ok and result.failure_class == "publish_unverified"
    assert len(fake.writes) == 1
    assert not (await db.execute(select(AuditLog.id).where(AuditLog.resource_id == intent.id))).first()


async def test_safe_provider_serialization_and_retry_are_proved_and_audited_once(db):
    fake = FakeCloudV2()
    fake.store = lambda body: body.replace("<br/>", "<br />").replace("&#x27;", "'")
    run, intent = await published_ready(db, fake)
    first = await publish(db, run, fake)
    second = await publish(db, run, fake, entry=2)
    assert first.ok and second.ok and len(fake.writes) == 1
    audits = (await db.execute(select(AuditLog).where(AuditLog.resource_id == intent.id))).scalars().all()
    assert len(audits) == 1
    assert "body" not in audits[0].details
    assert canonical_digest("<p>a&#x27;b<br/></p>") == canonical_digest("<p>a'b<br /></p>")


async def test_incomplete_and_duplicate_child_scan_never_certifies_absence(db):
    fake = FakeCloudV2(page_size=1)
    run, intent = await published_ready(db, fake)
    fake.faults["POST"] = apply_then(Crash())
    await crashed(db, publish(db, run, fake, worker="original"))
    await db.refresh(run)
    page = fake.children(PARENT)[0]
    fake.add_page("copy", fake.pages[page]["versions"][0]["storage"])
    refused = await publish(db, run, fake, entry=2, worker="original", reconcile=True)
    assert not refused.ok and refused.failure_class == "publish_unverified"
    assert len(fake.writes) == 1 and intent.state == "pending_reconcile"
    fake.overrides[f"GET {API}/pages/{PARENT}/direct-children"] = answer(200, {"results": [], "_links": {"next": "https://elsewhere.atlassian.net/wiki/api/v2/pages/x?cursor=x"}})
    refused = await publish(db, run, fake, entry=3, worker="original", reconcile=True)
    assert not refused.ok and refused.failure_class == "reconcile_incomplete"
    assert len(fake.writes) == 1 and intent.state == "pending_reconcile"


async def test_update_conflict_is_transport_status_and_never_overwrites_new_version(db):
    from tests.s1_publish_run_support import confirm, reserve
    fake = FakeCloudV2()
    run, _intent = await published_ready(db, fake)
    first = await publish(db, run, fake)
    next_intent = await reserve(db, run, fake, entry=2)
    await confirm(db, run, next_intent)
    fake.faults["PUT"] = answer(409, {"message": "irrelevant conflict body"})
    refused = await publish(db, run, fake, entry=3)
    assert not refused.ok and refused.failure_class == "page_changed"
    assert fake.pages[first.result["page_id"]]["versions"][-1]["number"] == 1
    assert next_intent.state == "never_started_certified"


async def test_malformed_pagination_and_version_answers_are_fail_closed():
    fake = FakeCloudV2()
    fake.overrides[f"GET {API}/pages/{PARENT}/direct-children"] = answer(200, {"results": [None]})
    async with CloudV2Client(SITE, {}, transport=fake.transport()) as client:
        assert not (await client.scan_direct_children(PARENT)).complete
    assert publication_body_hash("<p>x</p>") == "sha256:" + hashlib.sha256(b"<p>x</p>").hexdigest()


async def test_page_scoped_allowlist_refuses_profile_before_any_provider_request():
    from app.services.workflow_runs.documentation.confluence_v2_errors import V2ProfileRefusalError
    fake = FakeCloudV2()
    with pytest.raises(V2ProfileRefusalError, match="allowlists"):
        CloudV2Client(SITE, {"confluence_allowed_pages": [{"id": PARENT, "include_children": True}]},
                      transport=fake.transport())
    assert fake.requests == []


async def test_stable_intent_marker_survives_retried_pass_without_another_reservation(db):
    from tests.s1_publish_run_support import reserve
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    retried = await reserve(db, run, fake, entry=55)
    assert (retried.id, retried.operation_id, retried.marker) == (intent.id, intent.operation_id, intent.marker)
    assert not fake.writes


async def test_unreadable_candidate_and_stale_decision_never_publish(db):
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    decision = await db.get(WorkflowRunDecision, intent.decision_id)
    newer = WorkflowRunDecision(run_id=run.id, subject="publication", kind="confirmation", action="changed",
                                payload={}, payload_hash=payload_hash({}), decided_by=run.requested_by)
    db.add(newer)
    await db.commit()
    refused = await publish(db, run, fake)
    assert not refused.ok and not fake.writes
    assert intent.state == "approved"
    assert decision.action == "confirmed"


async def test_lost_reply_reconciles_approved_attempt_not_a_newer_redraft(db):
    from app.services.workflow_runs.phase_outputs import output_hash
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    fake.faults["POST"] = apply_then(Crash())
    await crashed(db, publish(db, run, fake, worker="original"))
    await db.refresh(run)
    outputs = dict(run.context["outputs"])
    record = {**outputs["feature_documentation"]["record"], "what": "A newer unapproved draft."}
    outputs["feature_documentation"] = {**outputs["feature_documentation"], "record": record,
                                        "hash": output_hash(record), "version": 2}
    run.context = {**run.context, "outputs": outputs}
    await db.commit()
    recovered = await publish(db, run, fake, entry=2, worker="original", reconcile=True)
    assert recovered.ok and len(fake.writes) == 1
    assert recovered.result["page"]["output_hash"] == intent.output_hash
    assert recovered.result["page"]["output_hash"] != output_hash(record)
    assert "A newer unapproved draft." not in fake.pages[recovered.result["page_id"]]["versions"][0]["storage"]


async def test_a_space_key_matches_without_case_as_in_confluence():
    """The space is "Coffe", the Workspace setting is stored "COFFE" and Confluence answers ``keys=COFFE`` with
    "Coffe"; the key comparison ignores case, so this is not refused as malformed."""
    fake = FakeCloudV2()
    fake.spaces = {"77": "Coffe"}
    async with CloudV2Client(SITE, {}, transport=fake.transport()) as client:
        space = await client.find_space("COFFE")
        assert (space.id, space.key) == ("77", "Coffe")
