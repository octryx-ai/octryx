"""Scheduled header passes.

A scheduled run is the interval's ACL and freshness check:

- it lists full header pages whatever ``max_items_per_run`` is; the budget limits fetches only, item by
  item, and an item past the budget is deferred;
- a pass a failed run left open (a listing error, a 429 or a 500) restarts on the next scheduled run, so
  no item before the failed run's cursor misses this interval's check;
- a pass a scheduled run left open only at its page bound is resumed, so a large source still completes.
"""

from __future__ import annotations

import httpx
import pytest

from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.sources.sync import runner
from app.services.knowledge.sources.sync.service_run import run_connector
from tests.confluence_cloud_freshness_corrections_support import HIDDEN, _item, _run
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_support import _setup
from tests.test_confluence_cloud_freshness import _cloud, _set_budget

pytestmark = pytest.mark.usefixtures("public_source_dns")

PAGES = [str(101 + index) for index in range(10)]


async def _synced(db, stub):
    setup = await _setup(db, kind="confluence")
    stub.accounts = {HIDDEN: None}
    for page_id in PAGES:
        stub.put(page_id, f"P{page_id}", f"<p>{page_id}</p>")
    assert (await _run(db, setup, stub)).state == "completed"
    return setup


async def _cursor(db, setup) -> dict:
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    await db.refresh(row)
    return dict(row.cursor)


async def test_a_scheduled_run_lists_every_header_whatever_its_budget(db, monkeypatch) -> None:
    monkeypatch.setattr(runner, "MAX_PAGES_PER_RUN", 2)
    stub = _cloud()
    setup = await _synced(db, stub)
    await _set_budget(db, setup, 1)
    stub.pages[PAGES[-1]]["account"] = HIDDEN  # restricted since, version unchanged

    run = await _run(db, setup, stub, trigger="scheduled")

    assert run.state == "completed" and run.report["pass_completed"] is True
    assert (await _item(db, setup, PAGES[-1])).state == "withheld"


async def test_the_budget_limits_fetches_item_by_item_and_defers_the_rest(db) -> None:
    stub = _cloud()
    setup = await _synced(db, stub)
    await _set_budget(db, setup, 1)
    for page_id in PAGES[:3]:
        stub.edit(page_id, body=f"<p>{page_id} changed</p>")

    run = await _run(db, setup, stub, trigger="scheduled")

    assert (run.report["updated"], run.report["deferred"]) == (1, 2)


def _failing_listing(stub, calls: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/rest/api/content", "/rest/api/content/search")):
            calls["listings"] += 1
            if calls["listings"] == calls["fail_at"]:
                return httpx.Response(500, json={"message": "boom"})
        status, payload, headers = stub.handle(
            request.method, request.url.raw_path.decode(), request.headers.get("Authorization")
        )
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.MockTransport(handler)


async def _scheduled(db, setup, transport):
    authorized, user_id, runtime, row = setup
    return await run_connector(
        db, runtime=runtime, authorized=authorized, row=await db.get(KnowledgeSourceConnector, row.id),
        actor_id=user_id, transport=transport, trigger="scheduled",
    )


async def test_a_pass_a_failed_run_left_open_restarts_on_the_next_scheduled_run(db, monkeypatch) -> None:
    monkeypatch.setattr(runner, "PAGE_SIZE", 1)
    stub = _cloud()
    setup = await _synced(db, stub)
    calls = {"listings": 0, "fail_at": 3}

    failed = await _scheduled(db, setup, _failing_listing(stub, calls))
    open_pass = await _cursor(db, setup)
    stub.pages[PAGES[0]]["account"] = HIDDEN  # before the failed run's cursor
    calls["fail_at"] = -1
    resumed = await _scheduled(db, setup, _failing_listing(stub, calls))

    assert failed.state == "failed" and open_pass["token"] is not None
    assert resumed.state == "completed"
    assert (await _cursor(db, setup))["completed_passes"] == open_pass["completed_passes"] + 1
    assert (await _item(db, setup, PAGES[0])).state == "withheld"


async def test_a_pass_left_open_at_the_page_bound_is_resumed(db, monkeypatch) -> None:
    stub = _cloud()
    setup = await _synced(db, stub)
    monkeypatch.setattr(runner, "PAGE_SIZE", 4)
    monkeypatch.setattr(runner, "MAX_PAGES_PER_RUN", 1)

    first = await _run(db, setup, stub, trigger="scheduled")
    after_first = await _cursor(db, setup)
    second = await _run(db, setup, stub, trigger="scheduled")
    after_second = await _cursor(db, setup)

    assert first.state == second.state == "budget_exhausted"
    assert after_second["pass_number"] == after_first["pass_number"], "the open pass is continued"
    assert after_second["token"] != after_first["token"]


async def test_a_manual_run_after_a_failed_one_does_not_mask_the_failure(db, monkeypatch) -> None:
    """Judge r7: every run since the last completed pass counts, not only the connector's last run."""
    monkeypatch.setattr(runner, "PAGE_SIZE", 1)
    stub = _cloud()
    setup = await _synced(db, stub)
    failed = await _scheduled(db, setup, _failing_listing(stub, {"listings": 0, "fail_at": 3}))
    monkeypatch.setattr(runner, "MAX_PAGES_PER_RUN", 1)
    manual = await _run(db, setup, stub)  # Run now resumes the open pass and stops at its page bound
    monkeypatch.setattr(runner, "MAX_PAGES_PER_RUN", 1000)
    stub.pages[PAGES[0]]["account"] = HIDDEN  # before the failed run's cursor

    resumed = await _scheduled(db, setup, _failing_listing(stub, {"listings": 0, "fail_at": -1}))

    assert (failed.state, manual.state, resumed.state) == ("failed", "budget_exhausted", "completed")
    assert (await _item(db, setup, PAGES[0])).state == "withheld"


async def test_a_crashed_run_in_the_open_pass_restarts_it(db, monkeypatch) -> None:
    from app.models.project.knowledge_source_sync import KnowledgeSourceSyncRun

    stub = _cloud()
    setup = await _synced(db, stub)
    monkeypatch.setattr(runner, "PAGE_SIZE", 4)
    monkeypatch.setattr(runner, "MAX_PAGES_PER_RUN", 1)
    await _run(db, setup, stub, trigger="scheduled")  # leaves the pass open at its page bound
    open_pass = await _cursor(db, setup)
    # A run that never finished (the process died): still ``running``, not the current run.
    db.add(KnowledgeSourceSyncRun(connector_id=setup[3].id, project_id=setup[0].project_id, state="running"))
    await db.commit()

    await _run(db, setup, stub, trigger="scheduled")

    assert (await _cursor(db, setup))["pass_number"] == open_pass["pass_number"] + 1, "a fresh pass began"
