"""Shared helpers for the test_s1_receipt_flow_* modules."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.main import app
from app.models import (
    BuiltInToolConfig,
    DocumentationWriteIntent,
    Project,
    Role,
    UserRole,
    WorkflowRun,
    WorkflowRunDecision,
)
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector, KnowledgeSourceSyncItem
from app.services.auth import get_current_user
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.access.source_acl import restrict_source
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.workflow_runs.documentation import audience_contract
from app.services.workflow_runs.documentation.knowledge_proof import ledger_binding
from app.services.workflow_runs.documentation.page import render_storage
from app.services.workflow_runs.pause import payload_hash
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_outsider, seed_workspace
from tests.knowledge_runtime_support import set_evidence_runtime

BASE = "/api/v1/workspaces"


INSTANCE = "https://docs.example.test/wiki"


PAGE_ID = "4242"


SOURCE_KEY = f"confluence.docs.{PAGE_ID}"


TITLE = "OCX-7: Totals round half up and the two percent fee"


RECORD = {
    "what": "Invoice totals round half up, and every payment carries a two percent fee.",
    "why": "Rounding down under-charged customers on half amounts; the fee covers the card provider's cost.",
    "how_to_use": "Nothing to configure: totals and fees apply to every new invoice after the release.",
}


CRITERIA = [
    {"id": "AC-1", "text": "Invoice totals round half up to the cent", "tests": ["test_round"], "manual_only": False},
    {"id": "AC-2", "text": "Every card payment carries the two percent provider fee", "tests": ["test_fee"],
     "manual_only": False},
]


NO_LINKS = {"ticket": {"key": "", "url": ""}, "pull_request": {"id": "", "url": ""}}


TEXT = (f"{TITLE}\n\nWhat\n\n{RECORD['what']}\n\nWhy\n\n{RECORD['why']}\n\nHow to use\n\n{RECORD['how_to_use']}\n\n"
        f"AC-1 {CRITERIA[0]['text']} test_round\n\nAC-2 {CRITERIA[1]['text']} test_fee\n").encode()


HASH = "sha256:" + "c" * 64


@pytest.fixture
def evidence_runtime():
    runtime, s3, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, s3, evidence_index
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def as_user():
    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


async def make_admin(db, user_id: str) -> None:
    role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=user_id, role_id=role.id))
    await db.flush()


def payload_for(run_id: str, criteria: list[dict] | None = None) -> dict:
    criteria = CRITERIA if criteria is None else criteria
    return {"subject": "publication", "title": TITLE, "acceptance_criteria": criteria,
            "body": render_storage(RECORD, criteria, NO_LINKS, run_id=run_id), "target": {"page_id": PAGE_ID}}


async def bind_publication(db, runtime, evidence_index, *, semantics: str = audience_contract.SEMANTICS_WORKSPACE,
                           criteria: list[dict] | None = None, audience: dict | None = None) -> SimpleNamespace:
    workspace = await seed_workspace(db)
    requester = await seed_member(db, workspace_id=workspace, role="admin")
    principal = await seed_member(db, workspace_id=workspace, role="member")
    if semantics == audience_contract.SEMANTICS_WORKSPACE:
        outsider = await seed_outsider(db)
    else:
        outsider = await seed_member(db, workspace_id=workspace, role="member")
    project = await db.get(Project, workspace)
    proof = {"semantics": semantics, "principal_user_id": principal, "outsider_user_id": outsider, "source_key": "docs"}
    config = {"feature_documentation": {"confluence_space_key": "DOCS", "audience_proof": audience or proof}}
    if semantics == audience_contract.SEMANTICS_SOURCE:
        config["knowledge_source_acl"] = {"enforce": True}  # test Workspace only: the dependency is met here
    project.config = config
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=workspace, is_active=True, config={
        "confluence_auth_mode": "basic",
        "confluence_url": INSTANCE, "confluence_username": "fixture-reader",
        "confluence_password": "s1-fixture-secret-never-export", "confluence_allowed_spaces": [
            {"space_key": "DOCS", "enabled": True}],
    }))
    await db.flush()
    author = await fetch_user(db, requester)
    authorized = await authorize_workspace(db, current_user=author, workspace_id=workspace, require_author=True)
    if semantics == audience_contract.SEMANTICS_SOURCE:
        await restrict_source(db, project_id=workspace, source_key=SOURCE_KEY, restriction="page_restriction",
                              member_emails=((await fetch_user(db, principal)).email,))
    ingested = await ingest_text_source(
        db, runtime=runtime, authorized=authorized, source_key=SOURCE_KEY, display_title=TITLE,
        declared_media_type="text/plain", data=TEXT, created_by=requester,
        source_url=f"{INSTANCE}/spaces/DOCS/pages/{PAGE_ID}", products=["payments"], version="9.9")
    projector = EvidenceProjector(runtime)
    while await projector.project_once(db, worker_id="s1-test", project_id=workspace) is not None:
        pass
    connector = KnowledgeSourceConnector(project_id=workspace, connector_key="docs", kind="confluence",
                                         scope={"spaces": ["DOCS"]}, products=["payments"])
    db.add(connector)
    await db.flush()
    db.add(KnowledgeSourceSyncItem(connector_id=connector.id, project_id=workspace, external_id=PAGE_ID,
                                   source_key=SOURCE_KEY, source_id=ingested.source_id,
                                   content_sha256=ingested.content_sha256, version_marker="1",
                                   source_instance=INSTANCE, state="ingested", last_outcome="created"))
    run = WorkflowRun(workflow_kind="phased", workflow_key="b-vnext", requested_by=requester, project_id=workspace,
                      current_node_id="audience_proof", node_state={"entry": 3}, status="waiting")
    db.add(run)
    await db.flush()
    payload = payload_for(run.id, criteria)
    payload["audience"] = {**(audience or proof), "workspace_id": workspace}
    decision = WorkflowRunDecision(run_id=run.id, node_id="confirm_publication", kind="confirmation",
                                   subject="publication", action="confirmed", payload=payload,
                                   payload_hash=payload_hash(payload), decided_by=requester)
    db.add(decision)
    await db.flush()
    now = utc_now()
    operation = uuid.uuid4().hex
    intent = DocumentationWriteIntent(
        operation_id=operation, marker=f"octryx-documentation:{run.id}:{operation}", run_id=run.id,
        node_id="confirm_publication", reserved_pass_key="confirm_publication#1", decision_id=decision.id,
        card_hash=decision.payload_hash, output_hash=HASH, body_hash=HASH, connection_id="default",
        instance=INSTANCE, space_id="98307", space_key="DOCS", parent_id="900", title=TITLE, operation="create",
        expected_version=1, state="sent_confirmed", state_version=3, claimed_by="worker-1", claimed_at=now,
        result_kind="provider_reply", result_page_id=PAGE_ID, result_version=1, result_storage_digest=HASH,
        approved_at=now, send_started_at=now, sent_confirmed_at=now)
    db.add(intent)
    await db.flush()
    binding = await ledger_binding(db, connector_id=connector.id, project_id=workspace, page_id=PAGE_ID,
                                   page_version=1, instance=INSTANCE)
    run.context = {"documentation": {"page_id": PAGE_ID, "version": 1, "instance": INSTANCE, "provenance": {
        "proven": True, "intent_id": intent.id, "page_id": PAGE_ID, "page_version": 1, "connector_key": "docs",
        "revision_id": binding.revision_id, "source_key": SOURCE_KEY,
        "digests": {"storage_digest": HASH, "view_raw_digest": "sha256:" + "d" * 64,
                    "document_html_digest": binding.revision_digest,
                    "index_refs_digest": binding.index_refs_digest}}}}
    await db.commit()
    return SimpleNamespace(workspace=workspace, requester=requester, principal=principal, outsider=outsider,
                           run=run, intent=intent, decision=decision, connector=connector, binding=binding)


async def prove(client, workspace: str, challenge: str, **extra) -> object:
    body = {"query_text": extra.pop("query_text", "x"), "proof_request": {"challenge_id": challenge, **extra}}
    return await client.post(f"{BASE}/{workspace}/knowledge/search", json=body)


async def state_of(db, receipt) -> str:
    await db.refresh(receipt)
    return receipt.state


@pytest.fixture(autouse=True)
def standalone_receipt_service(monkeypatch):
    from app.api.routes.knowledge import knowledge_evidence_search

    async def notify(_db, _run_id):
        return None

    monkeypatch.setattr(knowledge_evidence_search, "_notify_audience_proof", notify)
