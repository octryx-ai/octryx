"""Document and person identity: a document record merges identity and records its version claim, prose person noise is filtered, and a split identity consolidates when one record names both."""

from __future__ import annotations

import pytest

from app.services.knowledge_graph import get_neighbors, resolve_node_by_alias, upsert_node


@pytest.mark.asyncio
async def test_document_record_merges_identity_and_records_version_claim(db):
    import uuid as _uuid

    from app.services.knowledge_graph import get_claims_for_node
    from app.services.knowledge_graph.extractors import ingest_document_record

    token = _uuid.uuid4().hex[:8]
    page = {
        "title": f"Runbook {token}",
        "page_id": f"pg-{token}",
        "space_key": "ENG",
        "summary": "Operations runbook",
        "page_version": 7,
        "updated_when": "2026-07-01",
        "source_people": [
            {"role": "creator", "name": f"alice{token}", "display_name": f"Alice Example {token}",
             "email": f"alice{token}@example.com", "username": f"alice{token}"},
            {"role": "updated_by", "name": f"alice{token}", "display_name": f"Alice Example {token}",
             "email": f"alice{token}@example.com", "username": f"alice{token}"},
        ],
    }
    document = await ingest_document_record(db, project_id=None, page=page)
    assert document is not None

    # username, full name, and email all resolve to ONE person node.
    by_username = await resolve_node_by_alias(db, project_id=None, alias=f"alice{token}")
    by_fullname = await resolve_node_by_alias(db, project_id=None, alias=f"Alice Example {token}")
    by_email = await resolve_node_by_alias(db, project_id=None, alias=f"alice{token}@example.com")
    assert by_username is not None
    assert by_username.id == by_fullname.id == by_email.id

    neighbors = await get_neighbors(db, node_id=document.id)
    edge_types = {n["edge_type"] for n in neighbors}
    assert "authored" in edge_types and "contributed_to" in edge_types

    claims = await get_claims_for_node(db, node_id=document.id)
    assert claims and claims[0].valid_from_label == "v7"
    assert f"Alice Example {token}" in claims[0].statement


@pytest.mark.asyncio
async def test_prose_person_noise_filter(db):
    import uuid as _uuid

    from app.services.knowledge_graph import extract_graph_from_text

    token = _uuid.uuid4().hex[:8]

    async def fake_generate(prompt: str) -> str:
        if "MISSED" in prompt:
            return '{"entities": [], "relations": [], "claims": []}'
        return (
            '{"entities": ['
            '{"name": "Owner", "type": "person", "description": "generic"},'
            '{"name": "PM", "type": "person", "description": "generic"},'
            f'{{"name": "Jane Doe {token}", "type": "person", "description": "real engineer"}}'
            '], "relations": [], "claims": []}'
        )

    result = await extract_graph_from_text(
        db, project_id=None, text="Owner and PM discussed with Jane.",
        source_ref=f"doc:{token}", generate=fake_generate,
    )
    assert result["entities"] == 1  # only Jane survives
    node = await resolve_node_by_alias(db, project_id=None, alias=f"Jane Doe {token}")
    assert node is not None


@pytest.mark.asyncio
async def test_split_identity_consolidates_when_one_record_names_both(db):
    """A Jira-style full-name node and a Confluence-style username node merge
    deterministically when one source record carries both identifiers."""
    import uuid as _uuid

    from app.services.knowledge_graph.extractors import ingest_person_from_source

    token = _uuid.uuid4().hex[:8]
    full_name = f"Alice Example {token}"
    username = f"alice{token}"

    jira_node = await upsert_node(
        db, project_id=None, node_type="person", node_key=f"jira-{token}",
        display_name=full_name, description="from jira", embed=False,
    )
    confluence_node = await upsert_node(
        db, project_id=None, node_type="person", node_key=f"conf-{token}",
        display_name=username, description="from confluence", embed=False,
    )
    assert jira_node.id != confluence_node.id  # split identity exists

    merged = await ingest_person_from_source(
        db,
        project_id=None,
        person={"role": "creator", "name": username, "display_name": full_name,
                "email": f"{username}@example.com", "username": username},
        source_ref="confluence:consolidate",
    )
    assert merged is not None

    by_name = await resolve_node_by_alias(db, project_id=None, alias=full_name)
    by_user = await resolve_node_by_alias(db, project_id=None, alias=username)
    by_mail = await resolve_node_by_alias(db, project_id=None, alias=f"{username}@example.com")
    assert by_name.id == by_user.id == by_mail.id == merged.id

    await db.refresh(jira_node)
    await db.refresh(confluence_node)
    statuses = {jira_node.status, confluence_node.status}
    assert statuses == {"active", "merged"}
