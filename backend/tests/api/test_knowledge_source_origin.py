"""Contract: Knowledge → Documents tells synced from uploaded sources from stored lineage only, never from the
shape of a source key."""

from __future__ import annotations

import pytest

from app.api.routes.knowledge.knowledge_evidence_sources import get_knowledge_source, list_knowledge_sources
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user
from tests.knowledge_source_sync_support import WIKI, _setup
from tests.services.knowledge.sources.test_confluence_cloud_freshness import _cloud, _run

pytestmark = pytest.mark.usefixtures("public_source_dns")


async def _listed(db, workspace_id: str, user) -> dict[str, dict]:
    listing = await list_knowledge_sources(workspace_id, limit=None, cursor=None, query=None, current_user=user, db=db)
    return {source["source_key"]: source for source in listing["sources"]}


async def test_synced_sources_are_connector_origins_and_uploads_stay_uploads(db) -> None:
    setup = await _setup(db, kind="confluence")
    authorized, user_id, runtime, _ = setup
    user = await fetch_user(db, user_id)
    stub = _cloud()
    stub.put("101", "Runbook", "<p>Failover every Monday.</p>")
    stub.put("102", "Old page", "<p>Soon deleted.</p>")
    await _run(db, setup, stub)
    # An upload whose key has the shape of a synced key is still an upload.
    await ingest_text_source(
        db, runtime=runtime, authorized=authorized, source_key="confluence.ops.999", display_title="Notes",
        declared_media_type="text/plain", data=b"Uploaded notes.", created_by=user_id,
        source_url="https://example.test/notes",
    )

    sources = await _listed(db, authorized.project_id, user)
    assert sources["confluence.ops.101"]["origin"] == {
        "type": "connector",
        "connector_kind": "confluence",
        "connector_key": "ops",
        "url": f"{WIKI}/spaces/ENG/pages/101/Runbook",
        "removed_at_source": False,
    }
    assert sources["confluence.ops.999"]["origin"] == {"type": "upload"}

    stub.delete("102")
    stub.edit("101", title="Runbook v2")  # a new revision with a new link
    await _run(db, setup, stub)
    renamed = await get_knowledge_source(
        authorized.project_id, sources["confluence.ops.101"]["source_id"], current_user=user, db=db
    )
    assert renamed["origin"]["url"] == f"{WIKI}/spaces/ENG/pages/101/Runbook+v2", "the newest revision's link"
    old = sources["confluence.ops.102"]
    detail = await get_knowledge_source(authorized.project_id, old["source_id"], current_user=user, db=db)
    assert detail["origin"]["type"] == "connector" and detail["origin"]["removed_at_source"] is True
    assert detail["origin"]["url"] == f"{WIKI}/spaces/ENG/pages/102/Old+page"
    listed_again = (await _listed(db, authorized.project_id, user)).get("confluence.ops.102")
    assert listed_again is None or listed_again["origin"] == detail["origin"]
