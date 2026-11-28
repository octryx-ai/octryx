"""Contract: freshness that is correct, governed and visible."""

from __future__ import annotations

from datetime import UTC, timedelta

import pytest

from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.sources.sync.service_describe import describe_connector
from app.time_utils import utc_now
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_support import WIKI, _counts, _setup
from tests.services.knowledge.sources.test_confluence_cloud_freshness import _cloud, _origins, _set_budget
from tests.support.confluence_cloud_freshness_corrections_support import HIDDEN, _item, _on_listing, _run

pytestmark = pytest.mark.usefixtures("public_source_dns")


async def test_a_restriction_added_without_a_version_change_is_withheld_by_the_next_scheduled_run(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.accounts = {HIDDEN: None}
    stub.put("101", "Public", "<p>For everyone.</p>")
    stub.put("102", "Plan", "<p>Soon restricted.</p>")
    assert _counts(await _run(db, setup, stub))["created"] == 2

    stub.pages["102"]["account"] = HIDDEN  # restricted at the source, version and modified unchanged
    run = await _run(db, setup, stub, trigger="scheduled")
    assert run.report["mode"] == "incremental" and run.report["pass_completed"] is True
    assert _counts(run)["retired"] == 1 and run.report["withheld"] == 1
    assert run.report["withheld_reasons"] == {"restricted_acl": 1}
    assert (await _item(db, setup, "102")).state == "withheld"


async def test_a_scheduled_run_past_its_budget_still_checks_every_item_and_defers_only_fetches(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.accounts = {HIDDEN: None}
    for page_id in ("101", "102", "103"):
        stub.put(page_id, f"Page {page_id}", f"<p>{page_id}</p>")
    await _run(db, setup, stub)
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    clean_at = row.cursor["last_completed_at"]
    await _set_budget(db, setup, 1)
    stub.clock = utc_now().replace(tzinfo=UTC)
    stub.edit("101", body="<p>101 v2</p>")
    stub.edit("102", body="<p>102 v2</p>")
    stub.pages["103"]["account"] = HIDDEN

    run = await _run(db, setup, stub, trigger="scheduled")
    assert _counts(run)["updated"] == 1 and run.report["deferred"] == 1, "the budget counts fetched bodies only"
    assert run.report["withheld"] == 1 and (await _item(db, setup, "103")).state == "withheld"
    assert run.report["pass_completed"] is True and run.report["completed_with_failures"] is False
    await db.refresh(row)
    assert row.cursor["last_completed_at"] == clean_at, "a deferred fetch keeps the pass from counting as clean"


async def test_withheld_is_the_connectors_current_total_across_runs(db) -> None:
    setup = await _setup(db, kind="confluence")
    await _set_budget(db, setup, 2)
    stub = _cloud()
    stub.accounts = {HIDDEN: None}
    stub.put("101", "A", "<p>A</p>")
    stub.put("102", "B", "<p>B</p>")
    stub.put("103", "Hidden", "<p>C</p>", restricted_to_account=HIDDEN)
    assert (await _run(db, setup, stub)).state == "budget_exhausted"
    assert (await _run(db, setup, stub)).report["withheld"] == 1

    stub.edit("101", body="<p>A2</p>")
    stub.edit("102", body="<p>B2</p>")
    third = await _run(db, setup, stub)  # spends its budget on 101/102, never lists 103
    assert third.state == "budget_exhausted" and _counts(third)["skipped"] == 0
    assert third.report["withheld"] == 1, "still withheld at the source, so still counted"


async def test_a_failed_item_blocks_a_clean_pass_and_the_next_scheduled_run_retries_it(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "A", "<p>A</p>")
    stub.put("102", "B", "<p>B</p>")
    await _run(db, setup, stub)
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    clean_at = row.cursor["last_completed_at"]

    stub.edit("102", body="<p>B2</p>")
    failed = await _run(db, setup, stub, trigger="scheduled", failing={"102"})
    assert failed.state == "completed" and failed.report["completed_with_failures"] is True
    await db.refresh(row)
    freshness = (await describe_connector(db, row))["freshness"]
    assert row.cursor["last_completed_at"] == clean_at, "not a clean reconciliation"
    assert freshness["last_pass_failures"] >= 1 and freshness["last_pass_closed_at"] is not None

    # The change window no longer lists 102; the header pass retries it anyway.
    row.cursor = {**row.cursor, "changes_since": (utc_now() + timedelta(days=1)).isoformat()}
    await db.commit()
    retried = await _run(db, setup, stub, trigger="scheduled")
    assert _counts(retried)["updated"] == 1 and retried.report["completed_with_failures"] is False
    await db.refresh(row)
    assert row.cursor["last_completed_at"] != clean_at and row.cursor["last_pass_failures"] == 0


@pytest.mark.parametrize("base", ["https://wiki.example.test:99999/wiki", "https://[bad/wiki", 42])
async def test_malformed_response_links_never_fail_the_run(db, base) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "Runbook", "<p>A</p>")
    stub.put("102", "Spaced", "<p>B</p>")

    def change(payload: dict) -> None:
        payload["_links"]["base"] = base
        for result in payload["results"]:
            if result["id"] == "102":
                result["_links"]["webui"] = "/spaces/ENG/pages/102/a b"

    run = await _run(db, setup, stub, rewrite=_on_listing(change))
    assert run.state == "completed" and _counts(run)["created"] == 2
    assert await _origins(db, setup[0].project_id) == {
        f"{WIKI}/spaces/ENG/pages/101/Runbook",
        f"{WIKI}/pages/viewpage.action?pageId=102",
    }
    # The change listing (scheduled) takes the same fallback instead of failing over.
    stub.edit("101", body="<p>A2</p>")
    scheduled = await _run(db, setup, stub, trigger="scheduled", rewrite=_on_listing(change))
    assert scheduled.report["mode"] == "incremental" and _counts(scheduled)["updated"] == 1
