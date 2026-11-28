"""Restricted items are withheld or retired, one failing item or an emoji title never aborts the run, a bounded run resumes from its cursor, and the listing tells readers they cannot author."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.routes.knowledge.knowledge_source_connectors import list_workspace_connectors
from app.models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceRevisionOrigin
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.knowledge_source_sync_support import WIKI, FakeConfluence, FakeJira, _count_revisions, _counts, _run, _setup

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("public_source_dns")


async def test_restricted_items_are_withheld_and_a_newly_restricted_one_is_retired(db) -> None:
    setup = await _setup(db, kind="jira")
    authorized = setup[0]
    jira = FakeJira()
    jira.put("10001", "OPS-1", "Failover drill", "Public runbook.", "2026-09-01T10:00:00Z")
    jira.put("10002", "OPS-2", "Incident", "Confidential forensics.", "2026-09-02T10:00:00Z", security="Security team")

    first = await _run(db, setup, jira)
    jira.put("10001", "OPS-1", "Failover drill", "Public runbook.", "2026-09-05T10:00:00Z", security="Security team")
    second = await _run(db, setup, jira)

    assert _counts(first)["created"] == 1 and _counts(first)["skipped"] == 1
    withheld = next(o for o in first.outcomes if o["outcome"] == "skipped")
    assert withheld == {"external_id": "10002", "title": None, "outcome": "skipped", "reason": "restricted_acl"}
    assert _counts(second)["skipped"] == 2 and _counts(second)["retired"] == 1
    # The restricted issue's bytes never reached the ledger.
    assert await _count_revisions(db, authorized.project_id) == 1

    confluence_setup = await _setup(db, kind="confluence")
    wiki = FakeConfluence()
    wiki.put("100", "Runbook", "<h2>Failover</h2><p>Every Monday.</p>")
    wiki.put("200", "HR notes", "<p>Salaries.</p>", restricted_to=("hr-lead",))
    wiki.put("300", "HR child", "<p>Inherited.</p>", ancestors=("200",))
    run = await _run(db, confluence_setup, wiki)

    assert _counts(run)["created"] == 1 and _counts(run)["skipped"] == 2
    assert await _count_revisions(db, confluence_setup[0].project_id) == 1


async def test_one_failing_item_does_not_abort_the_run(db) -> None:
    setup = await _setup(db, kind="confluence")
    wiki = FakeConfluence()
    wiki.put("100", "Runbook", "<h2>Failover</h2><p>Every Monday.</p>")
    wiki.put("200", "Broken", "<p>Never fetched.</p>")
    wiki.put("300", "Escalation", "<h2>Escalation</h2><p>Call the duty manager.</p>")
    wiki.broken_bodies.add("200")

    run = await _run(db, setup, wiki)

    assert run.state == "completed" and _counts(run)["created"] == 2 and _counts(run)["failed"] == 1
    failed = next(o for o in run.outcomes if o["outcome"] == "failed")
    assert failed["external_id"] == "200" and failed["reason"] == "source_unavailable"
    origins = (await db.execute(select(KnowledgeSourceRevisionOrigin.source_url))).scalars().all()
    assert sorted(origins) == [f"{WIKI}/pages/viewpage.action?pageId=100", f"{WIKI}/pages/viewpage.action?pageId=300"]


async def test_an_emoji_with_a_variation_selector_in_a_title_is_synced_not_failed(db) -> None:
    # A title like "ACME-436: <gear emoji + U+FE0F> maintenance: ..." syncs instead of failing every pass
    # with invalid_request.
    setup = await _setup(db, kind="jira")
    jira = FakeJira()
    jira.put("10001", "OPS-1", "\u2699\ufe0f maintenance: remove old scripts", "Body.", "2026-09-01T10:00:00Z")

    run = await _run(db, setup, jira)

    assert run.state == "completed" and _counts(run)["created"] == 1 and _counts(run)["failed"] == 0
    titles = (await db.execute(select(KnowledgeEvidenceSource.display_title))).scalars().all()
    assert titles == ["OPS-1: \u2699 maintenance: remove old scripts"]


async def test_a_bounded_run_resumes_from_the_cursor_and_retires_nothing_early(db) -> None:
    setup = await _setup(db, kind="jira", max_items=2)
    jira = FakeJira()
    for index in range(1, 4):
        jira.put(f"1000{index}", f"OPS-{index}", f"Issue {index}", f"Body {index}.", "2026-09-01T10:00:00Z")

    first = await _run(db, setup, jira)
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    assert first.state == "budget_exhausted" and _counts(first)["created"] == 2
    assert row.cursor["token"] == "2" and row.cursor["completed_passes"] == 0

    second = await _run(db, setup, jira)
    assert second.state == "completed" and _counts(second)["created"] == 1 and _counts(second)["retired"] == 0


async def test_the_listing_tells_readers_they_cannot_author_and_round_trips_the_schedule(db) -> None:
    authorized, user_id, _, _ = await _setup(db, kind="jira")
    reader_id = await seed_member(db, workspace_id=authorized.project_id, role="member")

    author_view = await list_workspace_connectors(authorized.project_id, await fetch_user(db, user_id), db)
    reader_view = await list_workspace_connectors(authorized.project_id, await fetch_user(db, reader_id), db)

    assert author_view["may_author"] is True and reader_view["may_author"] is False
    assert reader_view["connectors"][0]["schedule"] == {"enabled": False, "interval_minutes": 360, "next_run_at": None}
