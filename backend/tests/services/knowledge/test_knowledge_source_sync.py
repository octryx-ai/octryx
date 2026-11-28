"""Source Sync: Confluence and Jira connectors feed the evidence ledger."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.project.knowledge_evidence import (
    KnowledgeRevisionScope,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_support import JIRA, FakeJira, _count_revisions, _counts, _run, _setup

pytestmark = pytest.mark.usefixtures("public_source_dns")


async def _drain(db, runtime) -> None:
    projector = EvidenceProjector(runtime)
    for _ in range(30):
        if await projector.project_once(db, worker_id="test") is None:
            return
    raise AssertionError("the outbox did not drain")


async def test_a_first_run_creates_linked_revisions_and_an_unchanged_rerun_creates_none(db) -> None:
    setup = await _setup(db, kind="jira")
    authorized = setup[0]
    jira = FakeJira()
    jira.put("10001", "OPS-1", "Failover drill", "The failover drill runs every Monday.", "2026-09-01T10:00:00Z")
    jira.put("10002", "OPS-2", "Backup restore", "Restore the backup weekly.", "2026-09-02T10:00:00Z")

    first = await _run(db, setup, jira)

    assert first.state == "completed" and _counts(first)["created"] == 2
    origins = (await db.execute(select(KnowledgeSourceRevisionOrigin.source_url))).scalars().all()
    assert sorted(origins) == [f"{JIRA}/browse/OPS-1", f"{JIRA}/browse/OPS-2"]
    assert {tuple(row) for row in (await db.execute(select(KnowledgeRevisionScope.products))).scalars()} == {
        ("acme-orders",)
    }

    second = await _run(db, setup, jira)
    row = await db.get(KnowledgeSourceConnector, setup[3].id)

    assert _counts(second) == {"created": 0, "updated": 0, "unchanged": 2, "retired": 0, "skipped": 0, "failed": 0}
    assert await _count_revisions(db, authorized.project_id) == 2
    assert row.cursor["completed_passes"] == 2 and row.cursor["pass_number"] == 2 and row.cursor["token"] is None
    assert row.last_run_id == second.id and row.run_lease_until is None


async def test_changed_content_is_one_new_revision_and_a_touch_without_change_is_none(db) -> None:
    setup = await _setup(db, kind="jira")
    jira = FakeJira()
    jira.put("10001", "OPS-1", "Failover drill", "The failover drill runs every Monday.", "2026-09-01T10:00:00Z")
    await _run(db, setup, jira)

    jira.put("10001", "OPS-1", "Failover drill", "The failover drill runs every Monday.", "2026-09-03T08:00:00Z")
    touched = await _run(db, setup, jira)
    jira.put("10001", "OPS-1", "Failover drill", "The failover drill runs every Tuesday.", "2026-09-04T08:00:00Z")
    changed = await _run(db, setup, jira)

    assert _counts(touched)["unchanged"] == 1 and _counts(changed)["updated"] == 1
    ordinals = (await db.execute(select(KnowledgeSourceRevision.revision_ordinal))).scalars().all()
    assert sorted(ordinals) == [1, 2]


async def test_an_item_gone_at_the_source_is_retired_and_no_longer_retrieved(db) -> None:
    setup = await _setup(db, kind="jira")
    authorized, _, runtime, _ = setup
    jira = FakeJira()
    jira.put("10001", "OPS-1", "Failover drill", "The failover drill runs every Monday.", "2026-09-01T10:00:00Z")
    jira.put("10002", "OPS-2", "Backup restore", "Restore the backup weekly.", "2026-09-02T10:00:00Z")
    await _run(db, setup, jira)
    await _drain(db, runtime)

    async def served(query: str) -> list[str]:
        result = await retrieve_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text=query)
        return [item.citation for item in result.evidence]

    assert await served("failover") != []
    del jira.issues["10001"]
    run = await _run(db, setup, jira)
    await _drain(db, runtime)

    assert _counts(run)["retired"] == 1 and _counts(run)["unchanged"] == 1
    assert [o["reason"] for o in run.outcomes if o["outcome"] == "retired"] == ["removed_at_source"]
    assert await served("failover") == []
    assert await served("backup") != []
