"""Confluence Cloud links and visibility: the chat tools cite the canonical link the sync stores, security pins keep followed links relative and under the REST API with the change listing asked from before the change point, and times, the last clean full pass and Knowledge enablement are exposed."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.api.routes.knowledge import knowledge_source_connectors as routes
from app.api.routes.knowledge._knowledge_connector_http import ConnectorConfigBody
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.projection import workspace_provisioning as enablement
from app.services.knowledge.sources.sync.confluence_links import canonical_page_url
from app.services.knowledge.sources.sync.service_describe import describe_connector, describe_run
from app.services.knowledge.sources.sync.service_run import run_connector
from app.time_utils import utc_now
from app.tools._confluence_evidence import with_page_source
from app.tools.confluence import _confluence_child_summary, _confluence_page_search_summary
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user
from tests.knowledge_source_sync_support import WIKI, _setup
from tests.services.knowledge.sources.test_confluence_cloud_freshness import _cloud, _origins
from tests.support.confluence_cloud_freshness_corrections_support import _on_listing, _run, _transport

pytestmark = pytest.mark.usefixtures("public_source_dns")


def test_the_chat_tools_cite_the_canonical_link_the_sync_stores() -> None:
    page = {"id": "101", "title": "Runbook", "version": {"number": 3},
            "_links": {"webui": "/spaces/ENG/pages/101/Runbook"}}
    canonical = f"{WIKI}/spaces/ENG/pages/101/Runbook"
    assert _confluence_page_search_summary(page, WIKI)["url"] == canonical
    assert _confluence_child_summary(page, WIKI)["source_url"] == canonical
    assert with_page_source(dict(page), WIKI)["source_url"] == canonical
    assert with_page_source({"id": "101", "_links": "x"}, WIKI)["source_url"] == (
        f"{WIKI}/pages/viewpage.action?pageId=101"
    )


async def test_security_a_next_link_must_be_relative(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "A", "<p>A</p>")
    next_link = "https://evil.example/wiki/rest/api/content?cursor=x"
    run = await _run(db, setup, stub, rewrite=_on_listing(lambda p: p["_links"].update(next=next_link)))
    assert (run.state, run.reason) == ("failed", "source_contract_violation")
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    assert "evil" not in str(row.cursor.get("token")), "a foreign link is never stored as the cursor"


async def test_security_a_followed_link_stays_under_the_rest_api(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "A", "<p>A</p>")
    next_link = "/wiki/rest/internal/admin?cursor=x"
    run = await _run(db, setup, stub, rewrite=_on_listing(lambda p: p["_links"].update(next=next_link)))
    assert (run.state, run.reason) == ("failed", "source_contract_violation")
    assert not any("/internal/" in request for request in stub.requests)


async def test_security_a_foreign_response_base_never_moves_a_link(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "Runbook", "<p>A</p>")
    run = await _run(db, setup, stub, rewrite=_on_listing(lambda p: p["_links"].update(base="https://evil.example/wiki")))
    assert run.state == "completed"
    assert await _origins(db, setup[0].project_id) == {f"{WIKI}/spaces/ENG/pages/101/Runbook"}
    assert canonical_page_url(WIKI, "101", webui="/x", response_base="https://evil.example/wiki") == f"{WIKI}/x"


async def test_security_the_change_listing_asks_from_before_the_change_point(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "A", "<p>A</p>")
    await _run(db, setup, stub)
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    changes_since = datetime.fromisoformat(row.cursor["changes_since"])
    seen: list = []
    await _run(db, setup, stub, trigger="scheduled", seen=seen)
    cql = next(url.params["cql"] for url in seen if url.path.endswith("/content/search"))
    since = datetime.strptime(cql.rsplit('"', 2)[1], "%Y-%m-%d %H:%M")
    # Covers the account's time zone (CQL reads local time, up to UTC+14) plus a margin.
    assert since <= changes_since - timedelta(hours=14)


async def test_times_carry_a_utc_offset_and_the_last_clean_full_pass_is_exposed(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    stub.put("101", "A", "<p>A</p>")
    run = describe_run(await _run(db, setup, stub))
    assert run["started_at"].endswith("+00:00") and run["finished_at"].endswith("+00:00")
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    row.next_scheduled_at = utc_now()
    await db.commit()
    described = await describe_connector(db, row)
    assert described["schedule"]["next_run_at"].endswith("+00:00")
    assert described["cursor"]["last_completed_at"].endswith("+00:00")
    freshness = described["freshness"]
    assert freshness["last_full_pass_at"].endswith("+00:00") and freshness["last_pass_failures"] == 0
    assert freshness["full_pass_in_progress"] is False and freshness["run_now_full_pass"] is True
    assert described["last_run"]["finished_at"].endswith("+00:00")


async def test_configure_and_run_now_ensure_knowledge_and_the_listing_shows_it(db, monkeypatch) -> None:
    authorized, user_id, runtime, _ = await _setup(db, kind="confluence")
    user = await fetch_user(db, user_id)
    answers = [enablement.WorkspaceKnowledgeEnablement("needs_configuration", "postgres_index_unavailable"),
               enablement.WorkspaceKnowledgeEnablement("ready", "postgres_index")]
    calls: list[str] = []

    def index_state():
        calls.append(workspace_id)
        return answers[min(len(calls), len(answers)) - 1]

    workspace_id = authorized.project_id
    monkeypatch.setattr(enablement, "_index_state", index_state)
    stub = _cloud()
    stub.put("101", "A", "<p>A</p>")
    monkeypatch.setattr(routes, "get_evidence_runtime", lambda: runtime)
    monkeypatch.setattr(routes, "run_connector", lambda db, **kw: run_connector(db, **kw, transport=_transport(stub)))
    workspace_id = authorized.project_id

    listing = await routes.list_workspace_connectors(workspace_id, user, db)
    assert listing["knowledge"] == {"state": "unknown", "outcome": None, "checked_at": None}
    body = ConnectorConfigBody(kind="confluence", spaces=["ENG"], products=["acme-orders"])
    configured = await routes.configure_workspace_connector(workspace_id, "second", body, user, db)
    assert configured["knowledge"]["state"] == "needs_configuration" and calls == [workspace_id]

    ran = await routes.run_workspace_connector(workspace_id, "second", user, db)
    assert ran["state"] == "completed" and ran["knowledge"]["state"] == "ready" and len(calls) == 2
    assert ran["knowledge"]["checked_at"].endswith("+00:00")
    await routes.run_workspace_connector(workspace_id, "second", user, db)
    assert len(calls) == 2, "ready stays ready; no repeated enablement"
    assert (await routes.list_workspace_connectors(workspace_id, user, db))["knowledge"]["state"] == "ready"
