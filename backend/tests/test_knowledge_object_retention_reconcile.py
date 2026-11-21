"""Operator-owned object reconciliation and retention.

Covers what the issue asks to be proven: unreferenced objects are detected per Workspace
without cross-Workspace disclosure, reconciliation is report-only, and no key, content address
or credential reaches a report, a payload or the agent surface.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.project.knowledge_object_retention import (
    FINDING_STATE_OBSERVED,
    RETENTION_MODE_REPORT_ONLY,
    KnowledgeObjectReconciliationFinding,
)
from app.services.knowledge.objects import (
    content_digest,
)
from app.services.knowledge.retention.reconcile import reconcile_workspace
from tests.knowledge_evidence_s3_support import PREFIX
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.knowledge_object_retention_support import (
    ABANDONED,
    OPERATOR,
    _abandon,
    _authorized,
    _ingest,
    _set_policy,
    _wired,
)

# --- reconciliation ---------------------------------------------------------


async def test_reconciliation_separates_governed_references_from_abandoned_objects(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    await _ingest(db, runtime, authorized)
    abandoned_key = await _abandon(runtime, client, authorized, age_hours=200)

    report = await reconcile_workspace(
        db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR
    )

    assert report.inventory_object_count == 2
    assert report.referenced_object_count == 1
    assert report.unreferenced_object_count == 1
    assert report.candidate_object_count == 1
    assert report.unreferenced_byte_size == len(ABANDONED)
    assert report.inventory_truncated is False
    assert report.mode == RETENTION_MODE_REPORT_ONLY
    finding = (
        await db.execute(
            select(KnowledgeObjectReconciliationFinding).where(
                KnowledgeObjectReconciliationFinding.run_id == report.run_id
            )
        )
    ).scalar_one()
    assert finding.object_key == abandoned_key
    assert finding.content_sha256 == content_digest(ABANDONED)
    assert finding.state == FINDING_STATE_OBSERVED and finding.age_eligible is True
    # Report-only: the object is still there after a run.
    assert (maintain.bucket, abandoned_key) in client.source.objects
    assert "DeleteObject" not in client.calls


async def test_an_object_younger_than_the_policy_bound_is_reported_but_not_a_candidate(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    await _abandon(runtime, client, authorized, age_hours=2)
    await _set_policy(db, workspace_id, min_age_hours=24)

    report = await reconcile_workspace(
        db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR
    )

    assert report.unreferenced_object_count == 1
    assert report.candidate_object_count == 0
    assert report.findings[0].age_eligible is False


async def test_a_run_never_looks_outside_its_own_workspace(db):
    first_id = await seed_workspace(db)
    second_id = await seed_workspace(db)
    first = await _authorized(db, first_id)
    second = await _authorized(db, second_id)
    runtime, maintain, client = _wired()
    first_key = await _abandon(runtime, client, first, age_hours=200)
    second_key = await _abandon(runtime, client, second, age_hours=200)
    assert first_key != second_key

    report = await reconcile_workspace(
        db, maintenance=maintain, project_id=first_id, requested_by=OPERATOR
    )

    assert report.inventory_object_count == 1
    assert report.unreferenced_object_count == 1
    # Every listing was bounded to this Workspace's own derived prefix.
    assert client.prefixes == [f"{PREFIX}/knowledge/octryx_ws_{first.workspace.value.hex}/"]
    finding = (
        await db.execute(
            select(KnowledgeObjectReconciliationFinding).where(
                KnowledgeObjectReconciliationFinding.run_id == report.run_id
            )
        )
    ).scalar_one()
    assert finding.object_key == first_key


async def test_keys_that_are_not_the_product_derivation_are_counted_and_never_findings(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    prefix = maintain.workspace_key_prefix(authorized.workspace)
    client.plant(maintain.bucket, f"{prefix}sha256/aa/bb/not-a-content-address", b"x", age_hours=500)
    client.plant(maintain.bucket, f"{prefix}stray-upload.txt", b"y", age_hours=500)
    await _abandon(runtime, client, authorized, age_hours=500)

    report = await reconcile_workspace(
        db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR
    )

    assert report.unrecognized_object_count == 2
    assert report.inventory_object_count == 1
    assert report.unreferenced_object_count == 1
    assert len(report.findings) == 1
