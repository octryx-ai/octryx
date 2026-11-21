"""Contract: ACL re-evaluation also on a resumed pass, and every ``get_link`` path check pinned.

Against the Cloud-shaped stub, through the real connector, runner and ledger, no network:

- a scheduled run never resumes a pass a manual run began (stopped at its budget): it begins a fresh
  header pass, so a restriction added to a page *before* the old cursor is enforced in that run;
- a pass a scheduled run began (a scope beyond one run's header limit) is resumed, not restarted, so
  large scopes still complete;
- a followed ``_links.next`` with ``//``, ``..`` or ``\\`` in its path is refused before any request.
"""

from __future__ import annotations

import pytest

from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from tests.confluence_cloud_freshness_corrections_support import HIDDEN, _item, _on_listing, _run
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_support import _setup
from tests.test_confluence_cloud_freshness import _cloud, _set_budget

pytestmark = pytest.mark.usefixtures("public_source_dns")


async def _manual_pass_stopped_after_101(db):
    setup = await _setup(db, kind="confluence")
    await _set_budget(db, setup, 1)
    stub = _cloud()
    stub.accounts = {HIDDEN: None}
    for page_id in ("101", "102", "103"):
        stub.put(page_id, f"Page {page_id}", f"<p>{page_id}</p>")
    first = await _run(db, setup, stub)
    assert first.state == "budget_exhausted" and (await _item(db, setup, "101")).state == "ingested"
    return setup, stub


async def test_a_scheduled_run_never_resumes_a_manual_pass_so_earlier_pages_are_rechecked(db) -> None:
    setup, stub = await _manual_pass_stopped_after_101(db)
    stub.pages["101"]["account"] = HIDDEN  # restricted after the open pass listed it, version unchanged

    run = await _run(db, setup, stub, trigger="scheduled")
    assert run.report["pass_completed"] is True and run.report["listed"] == 3, "a fresh header pass from the start"
    assert (await _item(db, setup, "101")).state == "withheld"
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    await db.refresh(row)
    assert row.cursor["pass_scheduled"] is False and row.cursor["token"] is None


async def test_a_pass_a_scheduled_run_began_is_resumed(db) -> None:
    setup, stub = await _manual_pass_stopped_after_101(db)
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    # As if a scheduled run had begun this pass and stopped at its header limit.
    row.cursor = {**row.cursor, "pass_scheduled": True}
    await db.commit()
    pass_number = row.cursor["pass_number"]

    run = await _run(db, setup, stub, trigger="scheduled")
    assert run.report["listed"] == 2, "continues after the cursor"
    await db.refresh(row)
    # Closed (one fetch deferred by the budget, so not a clean reconciliation).
    assert run.report["pass_completed"] is True and row.cursor["last_pass_closed_at"] is not None
    assert (await _item(db, setup, "101")).last_seen_pass == pass_number


@pytest.mark.parametrize("next_link", [
    "/wiki/rest/api//content?cursor=x",
    "/wiki/rest/api/../internal/admin?cursor=x",
    "/wiki/rest/api/content\\admin?cursor=x",
])
async def test_security_a_followed_link_path_is_never_traversed(db, next_link) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "A", "<p>A</p>")
    run = await _run(db, setup, stub, rewrite=_on_listing(lambda payload: payload["_links"].update(next=next_link)))
    assert (run.state, run.reason) == ("failed", "source_contract_violation")
    assert all(request in ("GET /wiki/rest/api/content", "GET /wiki/rest/api/content/101") for request in stub.requests)


async def test_a_scheduled_run_that_hits_its_header_limit_is_continued_by_the_next(db, monkeypatch) -> None:
    from app.services.knowledge.sources.sync import runner

    monkeypatch.setattr(runner, "PAGE_SIZE", 1)
    monkeypatch.setattr(runner, "MAX_PAGES_PER_RUN", 1)  # a scope beyond one run's header limit
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    for page_id in ("101", "102", "103"):
        stub.put(page_id, f"Page {page_id}", f"<p>{page_id}</p>")

    first = await _run(db, setup, stub, trigger="scheduled")
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    await db.refresh(row)
    assert first.report["listed"] == 1 and row.cursor["pass_scheduled"] is True
    second = await _run(db, setup, stub, trigger="scheduled")
    assert [outcome["external_id"] for outcome in second.outcomes] == ["102"], "resumed, not restarted"
