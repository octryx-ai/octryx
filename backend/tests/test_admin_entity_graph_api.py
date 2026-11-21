"""Admin entity-graph panel API: real gold-layer graph payloads, node detail,
and the retrieval preview (the exact context block an agent would get)."""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge_graph import add_claim, upsert_edge, upsert_node
from tests.conftest import ADMIN_PASSWORD


async def _login(client):
    resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 303


async def _seed_graph(db, token: str):
    repo = await upsert_node(
        db,
        project_id=None,
        node_type="repository",
        node_key=f"repo-acme-{token}",
        display_name=f"ACME/svc-{token}",
        description="Repository for the ACME service",
        aliases=[f"ACME/svc-{token}"],
    )
    module = await upsert_node(
        db,
        project_id=None,
        node_type="module",
        node_key=f"mod-acme-{token}",
        display_name=f"worker-{token}.py",
        description=f"Code module worker-{token}.py. Defines functions: run",
        aliases=[f"worker-{token}.py"],
        resolve_by_alias=False,
    )
    await upsert_edge(
        db,
        project_id=None,
        edge_type="part_of",
        source_node_id=module.id,
        target_node_id=repo.id,
        description=f"worker-{token}.py part of ACME/svc-{token}",
    )
    await add_claim(
        db,
        project_id=None,
        subject_node_id=repo.id,
        statement=f"ACME/svc-{token} code index: 1 code files",
        claim_type="code_index",
    )
    await db.commit()
    return repo, module


@pytest.mark.asyncio
async def test_entity_graph_returns_real_graph_with_stats(client, db):
    await _login(client)
    token = uuid.uuid4().hex[:8]
    repo, module = await _seed_graph(db, token)

    response = await client.get(
        f"/admin/chat/api/panel/knowledge/entity-graph?query=ACME/svc-{token}&max_nodes=20"
    )
    assert response.status_code == 200
    payload = response.json()
    names = {node["display_name"] for node in payload["nodes"]}
    assert f"ACME/svc-{token}" in names and f"worker-{token}.py" in names
    assert any(edge["edge_type"] == "part_of" for edge in payload["edges"])
    stats = payload["stats"]
    assert stats["total_nodes"] >= 2 and stats["total_claims"] >= 1
    assert stats["node_types"].get("repository", 0) >= 1


@pytest.mark.asyncio
async def test_entity_graph_focus_expands_neighborhood(client, db):
    await _login(client)
    token = uuid.uuid4().hex[:8]
    repo, module = await _seed_graph(db, token)

    response = await client.get(
        f"/admin/chat/api/panel/knowledge/entity-graph?focus_node_id={repo.id}&max_nodes=20"
    )
    assert response.status_code == 200
    ids = {node["id"] for node in response.json()["nodes"]}
    assert repo.id in ids and module.id in ids


@pytest.mark.asyncio
async def test_entity_graph_focus_expands_ring_by_ring(client, db):
    """Focusing a sparsely connected node must show its surroundings, not a
    two-node island: BFS continues ring by ring until the budget is used."""
    await _login(client)
    token = uuid.uuid4().hex[:8]
    repo, module = await _seed_graph(db, token)
    second = await upsert_node(
        db,
        project_id=None,
        node_type="module",
        node_key=f"mod-acme-b-{token}",
        display_name=f"helper-{token}.py",
        description="Second module",
        resolve_by_alias=False,
    )
    await upsert_edge(
        db,
        project_id=None,
        edge_type="part_of",
        source_node_id=second.id,
        target_node_id=repo.id,
        description=f"helper-{token}.py part of the repo",
    )
    await db.commit()

    # Focus on the FIRST module: repo is ring 1, the second module is ring 2.
    response = await client.get(
        f"/admin/chat/api/panel/knowledge/entity-graph?focus_node_id={module.id}&max_nodes=20"
    )
    assert response.status_code == 200
    ids = {node["id"] for node in response.json()["nodes"]}
    assert {module.id, repo.id, second.id} <= ids


@pytest.mark.asyncio
async def test_entity_graph_node_detail_has_aliases_claims_relations(client, db):
    await _login(client)
    token = uuid.uuid4().hex[:8]
    repo, module = await _seed_graph(db, token)

    response = await client.get(f"/admin/chat/api/panel/knowledge/entity-graph/node/{repo.id}")
    assert response.status_code == 200
    detail = response.json()
    assert f"ACME/svc-{token}" in detail["aliases"]
    assert any(claim["claim_type"] == "code_index" for claim in detail["claims"])
    assert any(
        rel["peer_name"] == f"worker-{token}.py" and rel["edge_type"] == "part_of"
        for rel in detail["relations"]
    )

    missing = await client.get(f"/admin/chat/api/panel/knowledge/entity-graph/node/{uuid.uuid4()}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_retrieval_preview_returns_context_block(client, db):
    await _login(client)
    token = uuid.uuid4().hex[:8]
    await _seed_graph(db, token)

    response = await client.post(
        "/admin/chat/api/panel/knowledge/retrieval-preview",
        json={"query": f"What is in ACME/svc-{token}?", "mode": "local", "node_limit": 5},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "local"
    assert any(e["display_name"] == f"ACME/svc-{token}" for e in payload["entities"])
    assert f"ACME/svc-{token}" in payload["context_block"]


@pytest.mark.asyncio
async def test_federation_endpoints_require_configured_key(client, db, monkeypatch):
    await _login(client)
    response = await client.post(
        "/admin/chat/api/panel/knowledge/entity-graph/federation/export", json={}
    )
    assert response.status_code == 409
    assert "needs_configuration" in response.json()["detail"]

    class _Settings:
        knowledge_federation_signing_key = "integration-test-signing-key"

    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _Settings())

    token = uuid.uuid4().hex[:8]
    await _seed_graph(db, token)
    response = await client.post(
        "/admin/chat/api/panel/knowledge/entity-graph/federation/export", json={}
    )
    assert response.status_code == 200
    package = response.json()
    assert package["format"] == "entity-graph-package/v1"
    assert package["signature"]["algorithm"].startswith("hmac") or package["signature"]["value"]

    imported = await client.post(
        "/admin/chat/api/panel/knowledge/entity-graph/federation/import",
        json={"package": package},
    )
    assert imported.status_code == 200
    stats = imported.json()
    assert stats["nodes_created"] == 0  # same instance: everything merges


@pytest.mark.asyncio
async def test_entity_graph_query_seeds_only_real_matches_and_names_them(client, db):
    """A query shows its matches (flagged) plus their neighbours, and says when nothing matched."""
    await _login(client)
    # A fixed token: the test embedding is a hash, so a random token makes the repository or the unrelated node a
    # semantic match (score >= SEMANTIC_MATCH_THRESHOLD) in about 1 of 200 runs.
    token = "e9a7f00d"
    repo, module = await _seed_graph(db, token)
    unrelated = await upsert_node(
        db,
        project_id=None,
        node_type="module",
        node_key=f"mod-unrelated-{token}",
        display_name=f"unrelated-{token}.py",
        description="Nothing to do with the query",
        resolve_by_alias=False,
    )
    await db.commit()

    response = await client.get(f"/admin/chat/api/panel/knowledge/entity-graph?query=worker-{token}.py&max_nodes=20")
    payload = response.json()
    flags = {node["id"]: node["matched"] for node in payload["nodes"]}
    assert module.id in payload["match_ids"] and flags[module.id] is True
    # The repository is shown as the match's neighbour, not as a match; the unrelated node not at all.
    assert flags.get(repo.id) is False
    assert unrelated.id not in flags
    assert payload["stats"]["matched_nodes"] == len(payload["match_ids"])

    empty = (
        await client.get(f"/admin/chat/api/panel/knowledge/entity-graph?query=qqxv-{token}-nomatch&max_nodes=20")
    ).json()
    assert empty["match_ids"] == [] and empty["nodes"] == []
    assert empty["stats"]["matched_nodes"] == 0

    browse = (await client.get("/admin/chat/api/panel/knowledge/entity-graph?max_nodes=20")).json()
    assert browse["match_ids"] is None and browse["stats"]["matched_nodes"] is None


@pytest.mark.asyncio
async def test_entity_graph_totals_and_neighbours_are_project_scoped(client, db):
    from sqlalchemy import func, select

    from app.models.project.knowledge_graph import KnowledgeGraphNode
    from tests.knowledge_evidence_seed_support import seed_workspace

    await _login(client)
    token = uuid.uuid4().hex[:8]
    own_project = await seed_workspace(db)
    other_project = await seed_workspace(db)
    own = await upsert_node(
        db,
        project_id=own_project,
        node_type="module",
        node_key=f"own-{token}",
        display_name=f"own-{token}.py",
        description="Own project module",
        resolve_by_alias=False,
    )
    foreign = await upsert_node(
        db,
        project_id=other_project,
        node_type="module",
        node_key=f"foreign-{token}",
        display_name=f"foreign-{token}.py",
        description="Other project module",
        resolve_by_alias=False,
    )
    await upsert_edge(
        db,
        project_id=own_project,
        edge_type="depends_on",
        source_node_id=own.id,
        target_node_id=foreign.id,
        description="cross-project edge",
    )
    await db.commit()

    payload = (
        await client.get(
            f"/admin/chat/api/panel/knowledge/entity-graph?project_id={own_project}&query=own-{token}.py&max_nodes=20"
        )
    ).json()
    ids = {node["id"] for node in payload["nodes"]}
    assert own.id in ids and foreign.id not in ids
    expected = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeGraphNode)
            .where(
                KnowledgeGraphNode.status == "active",
                (KnowledgeGraphNode.project_id == own_project) | (KnowledgeGraphNode.project_id.is_(None)),
            )
        )
    ).scalar_one()
    assert payload["stats"]["scope"] == "project"
    assert payload["stats"]["total_nodes"] == expected
    instance = (await client.get("/admin/chat/api/panel/knowledge/entity-graph?max_nodes=20")).json()
    assert instance["stats"]["total_nodes"] > payload["stats"]["total_nodes"]
