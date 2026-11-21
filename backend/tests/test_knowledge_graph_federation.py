"""Entity-graph federation (P8): signed portable packages, alias-first merge
on import, claim dedup, and tamper rejection."""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge_graph import add_claim, resolve_node_by_alias, upsert_edge, upsert_node
from app.services.knowledge_graph.federation import (
    EntityGraphPackageError,
    export_entity_graph_package,
    import_entity_graph_package,
    sign_entity_graph_package,
    verify_entity_graph_package,
)

SIGNING_KEY = "test-federation-signing-key"


async def _seed_global_graph(db, token: str):
    person = await upsert_node(
        db,
        project_id=None,
        node_type="person",
        node_key=f"hub-person-{token}",
        display_name=f"Hub Person {token}",
        description="Org-wide directory entry",
        aliases=[f"hubuser-{token}", f"hub.person.{token}@example.com"],
    )
    product = await upsert_node(
        db,
        project_id=None,
        node_type="product",
        node_key=f"hub-product-{token}",
        display_name=f"VendorSuite {token}",
        description="Vendor product tracked org-wide",
        aliases=[f"vendorsuite-{token}"],
    )
    await upsert_edge(
        db,
        project_id=None,
        edge_type="contributed_to",
        source_node_id=person.id,
        target_node_id=product.id,
        description=f"Hub Person {token} maintains VendorSuite {token}",
    )
    await add_claim(
        db,
        project_id=None,
        subject_node_id=product.id,
        statement=f"VendorSuite {token} release 4.0 published 2026-01-01",
        claim_type="release",
        valid_from_label="v4.0",
    )
    await db.commit()
    return person, product


@pytest.mark.asyncio
async def test_export_sign_verify_and_reimport_round_trip(db):
    token = uuid.uuid4().hex[:8]
    await _seed_global_graph(db, token)

    package = await export_entity_graph_package(db, source_instance="hub-test")
    assert package["counts"]["nodes"] >= 2
    exported_keys = {node["node_key"] for node in package["nodes"]}
    assert {f"hub-person-{token}", f"hub-product-{token}"} <= exported_keys
    person_entry = next(n for n in package["nodes"] if n["node_key"] == f"hub-person-{token}")
    assert f"hubuser-{token}" in person_entry["aliases"]

    signed = sign_entity_graph_package(package, signing_key=SIGNING_KEY)
    verify_entity_graph_package(signed, signing_key=SIGNING_KEY)

    # Re-import into the same instance: everything resolves to existing nodes.
    result = await import_entity_graph_package(db, signed, signing_key=SIGNING_KEY)
    assert result["nodes_created"] == 0
    assert result["nodes_merged"] >= 2
    # The release claim exists already — no duplicate.
    assert result["claims_added"] == 0


@pytest.mark.asyncio
async def test_import_merges_federated_person_into_local_node_via_alias(db):
    token = uuid.uuid4().hex[:8]
    local = await upsert_node(
        db,
        project_id=None,
        node_type="person",
        node_key=f"local-person-{token}",
        display_name=f"Team Local {token}",
        description="Local team member",
        aliases=[f"tlocal-{token}"],
    )
    await db.commit()

    # Hub package: DIFFERENT node key, but shares the username alias — one human.
    package = {
        "format": "entity-graph-package/v1",
        "source_instance": "hub-test",
        "generated_at": "2026-07-04T00:00:00+00:00",
        "scope": {"project_id": None, "node_types": None},
        "counts": {"nodes": 2, "edges": 1},
        "nodes": [
            {
                "node_type": "person",
                "node_key": f"hub-directory-{token}",
                "display_name": f"Team Local {token}",
                "description": "Org directory: platform engineer",
                "classification": "internal",
                "properties": {},
                "aliases": [f"tlocal-{token}", f"team.local.{token}@example.com"],
                "claims": [],
            },
            {
                "node_type": "product",
                "node_key": f"hub-tool-{token}",
                "display_name": f"OrgTool {token}",
                "description": "Shared org tool",
                "classification": "internal",
                "properties": {},
                "aliases": [f"orgtool-{token}"],
                "claims": [
                    {
                        "claim_type": "release",
                        "statement": f"OrgTool {token} 2.0 released",
                        "valid_from_label": "v2.0",
                        "valid_until_label": None,
                    }
                ],
            },
        ],
        "edges": [
            {
                "source": f"person:hub-directory-{token}",
                "target": f"product:hub-tool-{token}",
                "edge_type": "contributed_to",
                "description": "maintains",
            }
        ],
    }
    signed = sign_entity_graph_package(package, signing_key=SIGNING_KEY)
    result = await import_entity_graph_package(db, signed, signing_key=SIGNING_KEY)

    assert result["nodes_merged"] == 1  # person merged via alias
    assert result["nodes_created"] == 1  # product is new
    assert result["claims_added"] == 1
    assert result["edges_upserted"] == 1

    # Still ONE person node; description accumulated; edge attached to it.
    person = await resolve_node_by_alias(db, project_id=None, alias=f"tlocal-{token}")
    assert person is not None and person.id == local.id
    assert "Org directory" in person.description

    product = await resolve_node_by_alias(db, project_id=None, alias=f"orgtool-{token}")
    assert product is not None and product.trust_level == "federated"

    # Idempotent: re-import changes nothing.
    again = await import_entity_graph_package(db, signed, signing_key=SIGNING_KEY)
    assert again["nodes_created"] == 0 and again["claims_added"] == 0


@pytest.mark.asyncio
async def test_tampered_package_is_rejected(db):
    token = uuid.uuid4().hex[:8]
    await _seed_global_graph(db, token)
    package = await export_entity_graph_package(db, source_instance="hub-test")
    signed = sign_entity_graph_package(package, signing_key=SIGNING_KEY)

    tampered = dict(signed)
    tampered["nodes"] = list(signed["nodes"]) + [
        {
            "node_type": "person",
            "node_key": "evil",
            "display_name": "Injected",
            "description": "",
            "classification": "internal",
            "properties": {},
            "aliases": [],
            "claims": [],
        }
    ]
    with pytest.raises(EntityGraphPackageError):
        await import_entity_graph_package(db, tampered, signing_key=SIGNING_KEY)

    with pytest.raises(EntityGraphPackageError):
        verify_entity_graph_package(signed, signing_key="wrong-key-wrong-key")


@pytest.mark.asyncio
async def test_import_merges_into_project_scoped_local_node(db):
    """A hub directory entry must merge into the team's PROJECT-scoped node —
    never create a global duplicate of the same human."""
    from sqlalchemy import select

    from app.models import Project
    from app.models.project.knowledge_graph import KnowledgeGraphNode

    project = (await db.execute(select(Project))).scalars().first()
    token = uuid.uuid4().hex[:8]
    local = await upsert_node(
        db,
        project_id=project.id,
        node_type="person",
        node_key=f"team-person-{token}",
        display_name=f"Project Person {token}",
        description="Team member (project scope)",
        aliases=[f"puser-{token}"],
    )
    await db.commit()

    package = {
        "format": "entity-graph-package/v1",
        "source_instance": "hub-test",
        "generated_at": "2026-07-04T00:00:00+00:00",
        "scope": {"project_id": None, "node_types": None},
        "counts": {"nodes": 1, "edges": 0},
        "nodes": [
            {
                "node_type": "person",
                "node_key": f"hub-dir-{token}",
                "display_name": f"Project Person {token}",
                "description": "Org directory: security engineer",
                "classification": "internal",
                "properties": {},
                "aliases": [f"puser-{token}"],
                "claims": [],
            }
        ],
        "edges": [],
    }
    signed = sign_entity_graph_package(package, signing_key=SIGNING_KEY)
    result = await import_entity_graph_package(db, signed, signing_key=SIGNING_KEY)
    assert result["nodes_merged"] == 1 and result["nodes_created"] == 0

    # Exactly one person carries the alias; it is the project-scoped node,
    # now enriched with the hub description.
    people = (
        (
            await db.execute(
                select(KnowledgeGraphNode).where(
                    KnowledgeGraphNode.node_type == "person",
                    KnowledgeGraphNode.display_name == f"Project Person {token}",
                    KnowledgeGraphNode.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(people) == 1
    assert people[0].id == local.id and people[0].project_id == project.id
    assert "Org directory" in people[0].description
