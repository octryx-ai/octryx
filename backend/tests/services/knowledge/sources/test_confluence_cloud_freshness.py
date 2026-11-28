"""Contract: Confluence Cloud knowledge reaches the ledger with openable links and stays fresh, against the
Cloud-shaped stub through the real connector, runner and ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.api.routes.knowledge.knowledge_source_connectors import list_workspace_connectors
from app.models import BuiltInToolConfig, Project
from app.models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.sources.sync import http as sync_http
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.tools._confluence_evidence import page_url
from tests import source_stub_support as stubs
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user
from tests.knowledge_source_sync_support import WIKI, _count_revisions, _counts, _setup

pytestmark = pytest.mark.usefixtures("public_source_dns")

ORIGIN = "https://wiki.example.test"
OLD = datetime.now(UTC) - timedelta(days=2)


def _cloud() -> object:
    stub = stubs.confluence_stub.CloudConfluence(ORIGIN, space="ENG", principal="sync", secret="pw")
    stub.clock = OLD
    return stub


def _transport(stub) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        status, payload, headers = stub.handle(
            request.method, request.url.raw_path.decode(), request.headers.get("Authorization")
        )
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.MockTransport(handler)


async def _run(db, setup, stub, *, trigger: str = "manual"):
    authorized, user_id, runtime, row = setup
    row = await db.get(KnowledgeSourceConnector, row.id)
    return await run_connector(
        db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id, transport=_transport(stub),
        trigger=trigger,
    )


async def _origins(db, project_id: str) -> set[str]:
    rows = await db.execute(
        select(KnowledgeSourceRevisionOrigin.source_url)
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == KnowledgeSourceRevisionOrigin.revision_id)
        .where(KnowledgeSourceRevision.project_id == project_id)
    )
    return set(rows.scalars())


async def _titles(db, project_id: str) -> set[str]:
    rows = await db.execute(
        select(KnowledgeEvidenceSource.display_title).where(KnowledgeEvidenceSource.project_id == project_id)
    )
    return set(rows.scalars())


async def _set_budget(db, setup, items: int) -> None:
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    row.max_items_per_run = items
    await db.commit()


async def test_the_listing_follows_cloud_cursor_links_and_stores_canonical_links(db) -> None:
    setup = await _setup(db, kind="confluence")
    await _set_budget(db, setup, 2)
    stub = _cloud()
    for page_id, title in (("101", "Runbook"), ("102", "Escalation Policy"), ("103", "On-call")):
        stub.put(page_id, title, f"<p>{title} quokka</p>")

    first = await _run(db, setup, stub)
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    assert first.state == "budget_exhausted" and _counts(first)["created"] == 2
    assert row.cursor["token"].startswith("0:/rest/api/content?") and "cursor=" in row.cursor["token"]

    second = await _run(db, setup, stub)
    assert second.state == "completed" and _counts(second)["created"] == 1
    # The stub ignores offsets entirely: only the followed cursor reaches the third page.
    assert any("/rest/api/content" in request for request in stub.requests)
    assert await _origins(db, setup[0].project_id) == {
        f"{WIKI}/spaces/ENG/pages/101/Runbook",
        f"{WIKI}/spaces/ENG/pages/102/Escalation+Policy",
        f"{WIKI}/spaces/ENG/pages/103/On-call",
    }
    assert page_url(WIKI, "101", webui="/spaces/ENG/pages/101/Runbook") == f"{WIKI}/spaces/ENG/pages/101/Runbook"
    assert page_url(WIKI, "101") == f"{WIKI}/pages/viewpage.action?pageId=101"


async def test_scheduled_runs_list_changes_first_and_every_completed_pass_retires_deletions(db) -> None:
    setup = await _setup(db, kind="confluence")
    project_id = setup[0].project_id
    stub = _cloud()
    stub.put("101", "Runbook", "<p>Failover every Monday.</p>")
    stub.put("102", "Escalation", "<p>Call the duty manager.</p>")
    stub.put("103", "Old page", "<p>Soon deleted.</p>")
    full = await _run(db, setup, stub)
    assert full.report["mode"] == "full" and _counts(full)["created"] == 3
    assert await _count_revisions(db, project_id) == 3

    stub.clock = datetime.now(UTC)
    stub.edit("101", body="<p>Failover every Tuesday.</p>")
    stub.edit("102", title="Escalation Matrix")
    stub.put("104", "New page", "<p>Created after the full pass.</p>")
    stub.delete("103")
    stub.requests.clear()

    incremental = await _run(db, setup, stub, trigger="scheduled")
    assert incremental.state == "completed" and incremental.report["mode"] == "incremental"
    search = stub.requests.index("GET /wiki/rest/api/content/search")
    assert stub.requests.index("GET /wiki/rest/api/content") > search, "changes first, then the header pass"
    assert _counts(incremental) == {"created": 1, "updated": 2, "unchanged": 0, "retired": 1, "skipped": 0, "failed": 0}
    assert incremental.report["listed"] == 3 and len(incremental.outcomes) == 4, "each page once, plus the retired"
    assert incremental.report["pass_completed"] is True
    retired = next(o for o in incremental.outcomes if o["outcome"] == "retired")
    assert retired["external_id"] == "103" and retired["reason"] == "removed_at_source"
    assert await _count_revisions(db, project_id) == 6, "one new revision per change, none for the rest"
    assert "Escalation Matrix" in await _titles(db, project_id) and "Escalation" not in await _titles(db, project_id)
    assert f"{WIKI}/spaces/ENG/pages/102/Escalation+Matrix" in await _origins(db, project_id)

    again = await _run(db, setup, stub, trigger="scheduled")
    assert again.report["mode"] == "incremental" and _counts(again)["unchanged"] == 3
    assert await _count_revisions(db, project_id) == 6, "re-listed unchanged pages make no revision"
    assert again.report["listed"] == 3 and _counts(again)["retired"] == 0


async def test_a_failing_change_listing_reconciles_fully_in_the_same_run(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "Runbook", "<p>A</p>")
    stub.put("102", "Gone soon", "<p>B</p>")
    await _run(db, setup, stub)
    stub.delete("102")
    stub.search_status = 400

    run = await _run(db, setup, stub, trigger="scheduled")
    assert run.state == "completed" and run.report["mode"] == "incremental_fallback"
    assert _counts(run)["retired"] == 1 and _counts(run)["unchanged"] == 1

    stub.search_status = None
    manual = await _run(db, setup, stub)
    assert manual.report["mode"] == "full"


async def test_retry_after_is_honoured_within_bounds_and_otherwise_fails_with_its_reason(db, monkeypatch) -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(sync_http, "_sleep", sleep)
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "Runbook", "<p>A</p>")

    stub.throttle = [(429, "2")]
    assert (await _run(db, setup, stub)).state == "completed" and waits == [2.0]

    for throttle, reason in (
        ([(429, None)], "source_rate_limited"),
        ([(429, "120")], "source_rate_limited"),
        ([(503, "1"), (503, "1"), (503, "1")], "source_unavailable"),
    ):
        waits.clear()
        stub.throttle = list(throttle)
        run = await _run(db, setup, stub)
        assert (run.state, run.reason) == ("failed", reason)
        assert len(waits) <= 2 and all(wait <= sync_http.MAX_RETRY_AFTER_SECONDS for wait in waits)
        stub.throttle = []


@pytest.mark.parametrize("enforce", [False, True])
async def test_a_restricted_page_is_withheld_and_counted(db, enforce) -> None:
    setup = await _setup(db, kind="confluence")
    if enforce:
        project = await db.get(Project, setup[0].project_id)
        project.config = {**(project.config or {}), "knowledge_source_acl": {"enforce": True}}
        await db.commit()
    stub = _cloud()
    stub.accounts = {"557058:hidden": None}
    stub.put("101", "Public", "<p>For everyone.</p>")
    stub.put("102", "Secret plan", "<p>Restricted.</p>", restricted_to_account="557058:hidden")

    run = await _run(db, setup, stub)
    assert _counts(run)["created"] == 1 and run.report["withheld"] == 1
    withheld = next(o for o in run.outcomes if o["outcome"] == "skipped")
    assert withheld["reason"] == ("acl_unresolved" if enforce else "restricted_acl") and withheld["title"] is None
    assert "Secret plan" not in await _titles(db, setup[0].project_id)


async def test_a_bare_cloud_url_is_refused_at_configure_and_run(db) -> None:
    setup = await _setup(db, kind="confluence")
    authorized, user_id, runtime, row = setup
    entry = (await db.execute(select(BuiltInToolConfig).where(BuiltInToolConfig.project_id == authorized.project_id))).scalar_one()
    entry.config = {**entry.config, "confluence_url": "https://your-site.atlassian.net"}
    await db.commit()
    config = validate_config(connector_key="cloud", kind="confluence", spaces=["ENG"])
    with pytest.raises(ConnectorError) as refused:
        await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)
    assert refused.value.reason == "confluence_cloud_url_without_wiki"
    run = await _run(db, setup, _cloud())
    assert (run.state, run.reason) == ("needs_configuration", "confluence_cloud_url_without_wiki")


async def test_the_listing_says_whether_this_instance_runs_schedules(db, monkeypatch) -> None:
    authorized, user_id, _, _ = await _setup(db, kind="confluence")
    user = await fetch_user(db, user_id)
    monkeypatch.delenv("OCTRYX_ENABLE_KNOWLEDGE_SOURCE_SYNC_SCHEDULER", raising=False)
    assert (await list_workspace_connectors(authorized.project_id, user, db))["instance_scheduler_enabled"] is False
    monkeypatch.setenv("OCTRYX_ENABLE_KNOWLEDGE_SOURCE_SYNC_SCHEDULER", "true")
    monkeypatch.delenv("OCTRYX_DISABLE_BACKGROUND_WORKERS", raising=False)
    assert (await list_workspace_connectors(authorized.project_id, user, db))["instance_scheduler_enabled"] is True
    # The api of a worker split runs no background workers itself; the instance still runs schedules (worker pod).
    monkeypatch.setenv("OCTRYX_DISABLE_BACKGROUND_WORKERS", "1")
    assert (await list_workspace_connectors(authorized.project_id, user, db))["instance_scheduler_enabled"] is True
