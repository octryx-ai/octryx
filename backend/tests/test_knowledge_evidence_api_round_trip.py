"""Searching without an index, the transport's request bounds and the full HTTP round trip from upload through projection and search to citation and the listed products."""

from __future__ import annotations

from app.services.knowledge.ledger.queries import MAX_SOURCE_LIMIT
from app.services.knowledge.retrieval.evidence import MAX_RESULT_LIMIT
from tests.knowledge_evidence_api_support import BASE, TEXT, _upload, as_user, evidence_runtime  # noqa: F401
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace


async def test_searching_a_workspace_without_an_index_is_an_explicit_state(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id = await seed_workspace(db)
    author = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(author)

    response = await client.post(f"{BASE}/{workspace_id}/knowledge/search", json={"query_text": "datacenter"})

    # Never ingested on a configured instance: no sources yet, not a broken instance (E1).
    assert response.status_code == 409
    assert response.json()["detail"] == "This Workspace has no knowledge sources yet. Add a source to search it."


async def test_request_bounds_are_enforced_by_the_transport(client, db, as_user, evidence_runtime):  # noqa: F811
    """Finding 4: a limit outside the documented maximum is refused, never clamped."""
    workspace_id = await seed_workspace(db)
    author = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(author)

    for payload in (
        {"query_text": ""},
        {"query_text": "x" * 2001},
        {"query_text": "ok", "limit": 0},
        {"query_text": "ok", "limit": MAX_RESULT_LIMIT + 1},
        {},
    ):
        response = await client.post(f"{BASE}/{workspace_id}/knowledge/search", json=payload)
        assert response.status_code == 422, payload

    # The source list declares its own bound, so it is part of the contract too.
    for limit in (0, MAX_SOURCE_LIMIT + 1):
        listed = await client.get(f"{BASE}/{workspace_id}/knowledge/sources", params={"limit": limit})
        assert listed.status_code == 422, limit
    accepted = await client.get(f"{BASE}/{workspace_id}/knowledge/sources", params={"limit": MAX_SOURCE_LIMIT})
    assert accepted.status_code == 200


# --- the full round trip ----------------------------------------------------


async def test_upload_projection_search_and_citation_over_http(client, db, as_user, evidence_runtime):  # noqa: F811
    _, _, evidence_index = evidence_runtime
    workspace_id = await seed_workspace(db)
    author = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(author)

    created = await client.post(f"{BASE}/{workspace_id}/knowledge/sources", **_upload(TEXT))
    assert created.status_code == 201
    body = created.json()
    assert body["created"] is True and body["span_count"] == 2 and body["projection"] == "pending"
    assert body["media_type"] == "text/plain"
    # The client-supplied file name is never echoed or used as an identity.
    assert "ignored-name.txt" not in created.text

    repeat = await client.post(f"{BASE}/{workspace_id}/knowledge/sources", **_upload(TEXT))
    assert repeat.status_code == 201 and repeat.json()["created"] is False
    assert repeat.json()["revision_id"] == body["revision_id"]

    listed = await client.get(f"{BASE}/{workspace_id}/knowledge/sources")
    assert listed.status_code == 200
    assert listed.json()["projection_backlog"] == {"pending": 1}

    projected = await client.post(f"{BASE}/{workspace_id}/knowledge/projection/run")
    assert projected.status_code == 200
    assert projected.json()["applied"] is True and projected.json()["spans_projected"] == 2

    drained = await client.post(f"{BASE}/{workspace_id}/knowledge/projection/run")
    assert drained.json()["claimed"] is False

    found = await client.post(
        f"{BASE}/{workspace_id}/knowledge/search", json={"query_text": "datacenter", "limit": 5}
    )
    assert found.status_code == 200
    evidence = found.json()["evidence"]
    assert len(evidence) == 1
    hit = evidence[0]
    assert hit["revision_id"] == body["revision_id"]
    assert hit["content_sha256"] == body["content_sha256"]
    assert hit["span_ordinal"] == 1
    assert "rev 1" in hit["citation"] and "chars " in hit["citation"]
    assert "Zurich datacenter" in hit["text"]
    # No storage or database topology is exposed to a Workspace reader.
    for forbidden in ("octryx_ws_", "sha256/", "octryx-knowledge-test", "127.0.0.1", "plainto_tsquery"):
        assert forbidden not in found.text
    # Where the hit comes from, in the reader's words, and when this version arrived.
    assert hit["origin"] == {"kind": "upload", "connector_key": None, "url": None, "source_changed_at": None}
    assert hit["container"] is None
    assert isinstance(hit["changed_at"], str) and hit["changed_at"][:4].isdigit()
    timings = found.json()["timings_ms"]
    assert set(timings) == {"total", "stages", "workspaces"}
    assert isinstance(timings["total"], int) and "lexical" in timings["stages"]
    assert all("total" in stages for stages in timings["workspaces"].values())

    window = await client.get(f"{BASE}/{workspace_id}/knowledge/evidence/{hit['evidence_key']}/window?window=1")
    assert window.status_code == 200
    passages = window.json()["passages"]
    assert [item["is_hit"] for item in passages].count(True) == 1
    assert any("Zurich datacenter" in item["text"] for item in passages if item["is_hit"])
    assert window.json()["source_title"] == "Runbook" and window.json()["current"] is True
    unknown = await client.get(f"{BASE}/{workspace_id}/knowledge/evidence/00000000-0000-0000-0000-000000000000:1/window")
    assert unknown.status_code in (400, 404)

    detail = await client.get(f"{BASE}/{workspace_id}/knowledge/sources/{body['source_id']}")
    assert detail.status_code == 200
    revisions = detail.json()["revisions"]
    assert [item["revision_ordinal"] for item in revisions] == [1]
    assert revisions[0]["state"] == "projected"
    assert "object_key" not in revisions[0] and "object_bucket" not in revisions[0]


async def test_an_upload_carries_its_products_and_the_workspace_lists_them(client, db, as_user, evidence_runtime):  # noqa: F811
    _, _, evidence_index = evidence_runtime
    workspace_id = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(owner)
    upload = _upload(TEXT)
    upload["data"] |= {"products": "spring-boot, Spring-Boot", "version": "4.0"}
    created = await client.post(f"{BASE}/{workspace_id}/knowledge/sources", **upload)
    refused = _upload(TEXT, source_key="other")
    refused["data"] |= {"products": "spring boot"}

    assert created.status_code == 201
    assert (await client.post(f"{BASE}/{workspace_id}/knowledge/sources", **refused)).status_code == 400
    await client.post(f"{BASE}/{workspace_id}/knowledge/projection/run")
    listed = await client.get(f"{BASE}/{workspace_id}/knowledge/products")
    assert listed.status_code == 200 and listed.json()["products"] == {"spring-boot": ["4.0"]}
