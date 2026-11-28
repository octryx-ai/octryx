"""Contract: connector health times are ISO 8601 UTC with an offset, and a page listed by both scheduled passes is
counted once."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models import Project
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.connector_health import upsert_connector_health
from app.time_utils import utc_now
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_support import _setup
from tests.services.knowledge.sources.test_confluence_cloud_freshness import _cloud
from tests.support.confluence_cloud_freshness_corrections_support import _run

PANEL = "/admin/chat/api/panel"


def _offset(value: str) -> bool:
    return datetime.fromisoformat(value).utcoffset() is not None and value.endswith("+00:00")


async def test_b1_every_connector_health_time_carries_a_utc_offset(admin_client, db) -> None:
    project = Project(name=f"health-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.commit()
    for project_id in (None, project.id):
        await upsert_connector_health(db, connector_name="confluence", project_id=project_id, status="error",
                                      response_time_ms=12, error="HTTP 401", details="HTTP 401")
    await db.commit()

    cards = (await admin_client.get(f"{PANEL}/connectors")).json()
    cards = cards if isinstance(cards, list) else cards["connectors"]
    confluence = next(card for card in cards if card.get("tool_name", card.get("connector_name")) == "confluence")
    assert _offset(confluence["health"]["last_checked"]) and _offset(confluence["health"]["updated_at"])
    log = (await admin_client.get(f"{PANEL}/connectors/confluence/health-log")).json()
    entries = log if isinstance(log, list) else log.get("entries") or log.get("items") or log.get("log")
    assert entries and all(_offset(entry["checked_at"]) for entry in entries)
    workspace = (await admin_client.get(f"{PANEL}/projects/{project.id}/connectors/confluence/connection")).json()
    assert _offset(workspace["health"]["last_checked"]) and _offset(workspace["health"]["updated_at"])


@pytest.mark.usefixtures("public_source_dns")
async def test_b2_a_page_listed_by_both_listings_counts_once(db) -> None:
    setup = await _setup(db, kind="confluence")
    stub = _cloud()
    for page_id in ("101", "102", "103"):
        stub.put(page_id, f"Page {page_id}", f"<p>{page_id}</p>")
    await _run(db, setup, stub)
    row = await db.get(KnowledgeSourceConnector, setup[3].id)
    clean_at = row.cursor["last_completed_at"]
    stub.clock = utc_now().replace(tzinfo=UTC)  # inside the change window: both listings see the edits
    stub.edit("101", body="<p>101 v2</p>")
    stub.edit("102", body="<p>102 v2</p>")

    seen: list = []
    run = await _run(db, setup, stub, trigger="scheduled", failing={"102"}, seen=seen)
    assert run.report["mode"] == "incremental"
    assert sum(url.path.endswith("/content/102") for url in seen) == 1, "fetched once, by the change listing"
    ids = [outcome["external_id"] for outcome in run.outcomes]
    assert sorted(ids) == ["101", "102", "103"], "the item table lists each page once"
    assert (run.report["updated"], run.report["failed"], run.report["unchanged"]) == (1, 1, 1)
    assert run.report["listed"] == 3
    await db.refresh(row)
    assert row.cursor["last_completed_at"] == clean_at, "a page that failed in the change listing blocks a clean pass"
    assert row.cursor["last_pass_failures"] == 1
