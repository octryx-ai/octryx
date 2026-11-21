"""A search hit names its system, its space or project and when its version arrived.

Read from stored lineage only (``retrieval/hit_origin.py``): a synced Confluence page is ``confluence`` with its
connector key, its stored link, its connector's one space and its revision's arrival time; an upload is
``upload`` even when its key looks like a connector key; a Jira project comes from the issue key, never from a
title; a Confluence connector with several spaces names none (the page's own space is not stored).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceRevision
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.retrieval.hit_origin import _container, hit_origins
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_support import WIKI, _setup
from tests.test_confluence_cloud_freshness import _cloud, _run

pytestmark = pytest.mark.usefixtures("public_source_dns")


async def _ref(db, workspace_id: str, source_key: str) -> tuple[str, str, str]:
    source_id = (
        await db.execute(
            select(KnowledgeEvidenceSource.id).where(
                KnowledgeEvidenceSource.project_id == workspace_id, KnowledgeEvidenceSource.source_key == source_key
            )
        )
    ).scalar_one()
    revision_id = (
        await db.execute(
            select(KnowledgeSourceRevision.id)
            .where(KnowledgeSourceRevision.source_id == source_id)
            .order_by(KnowledgeSourceRevision.revision_ordinal.desc())
            .limit(1)
        )
    ).scalar_one()
    return workspace_id, source_id, revision_id


async def test_a_synced_page_and_an_upload_name_their_origin(db) -> None:
    setup = await _setup(db, kind="confluence")
    authorized, user_id, runtime, _ = setup
    stub = _cloud()
    stub.put("101", "Runbook", "<p>Failover every Monday.</p>")
    await _run(db, setup, stub)
    await ingest_text_source(
        db, runtime=runtime, authorized=authorized, source_key="confluence.ops.999", display_title="Notes",
        declared_media_type="text/plain", data=b"Uploaded notes.", created_by=user_id,
    )
    page = await _ref(db, authorized.project_id, "confluence.ops.101")
    upload = await _ref(db, authorized.project_id, "confluence.ops.999")

    origins = await hit_origins(db, [page, upload, page])

    assert origins[page]["origin"] == {
        "kind": "confluence", "connector_key": "ops", "url": f"{WIKI}/spaces/ENG/pages/101/Runbook",
        "source_changed_at": stub.pages["101"]["modified"].isoformat(),  # the page's version.when, not our sync
    }
    assert origins[page]["container"] == "ENG", "the connector reads exactly one space"
    assert isinstance(origins[page]["changed_at"], str)
    assert origins[upload] == {
        "origin": {"kind": "upload", "connector_key": None, "url": None, "source_changed_at": None},
        "container": None,
        "changed_at": origins[upload]["changed_at"],
    }
    assert origins[upload]["changed_at"] is not None


async def test_unknown_references_answer_without_lineage(db) -> None:
    setup = await _setup(db, kind="confluence")
    authorized = setup[0]
    missing = (authorized.project_id, "00000000-0000-0000-0000-000000000000", "00000000-0000-0000-0000-000000000001")
    assert (await hit_origins(db, [missing]))[missing] == {"origin": None, "container": None, "changed_at": None}
    assert await hit_origins(db, []) == {}


def test_the_container_comes_from_stored_identifiers_only() -> None:
    assert _container("jira", "ACME-117", {}) == "ACME"
    assert _container("jira", "not an issue key", {}) is None
    assert _container("confluence", "101", {"spaces": ["ENG"]}) == "ENG"
    assert _container("confluence", "101", {"spaces": ["ENG", "OPS"]}) is None, "several spaces: the page's is unknown"
    assert _container("confluence", "101", {"spaces": ["ENG"], "page_trees": [{"space_key": "ENG", "root": 1}]}) == "ENG"
    assert _container("servicenow", "INC0001", {}) is None


def test_source_dates_read_every_source_format_and_never_fail() -> None:
    from app.services.knowledge.sources.sync.source_dates import source_date

    assert source_date("2026-10-04T12:00:00.000Z").isoformat() == "2026-10-04T12:00:00+00:00"  # Confluence
    assert source_date("2026-10-04T14:00:00.000+0200").isoformat() == "2026-10-04T12:00:00+00:00"  # Jira
    assert source_date("2026-10-04 12:00:00").isoformat() == "2026-10-04T12:00:00+00:00"  # ServiceNow (UTC)
    assert source_date("yesterday") is None and source_date(None) is None
