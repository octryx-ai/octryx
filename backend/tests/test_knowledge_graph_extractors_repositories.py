"""Repository, code graph and release records: commit authors without bots, module internals, modules kept apart across repositories, and release nodes with their tracker link."""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge_graph import get_neighbors, ingest_code_structure, resolve_node_by_alias


@pytest.mark.asyncio
async def test_repository_record_links_commit_authors_filters_bots(db):
    import uuid as _uuid

    from app.services.knowledge_graph.extractors import ingest_repository_record

    token = _uuid.uuid4().hex[:8]
    record = {
        "repository": f"OCX/repo-{token}",
        "label": f"OCX/repo-{token}",
        "branch_name": "master",
        "current_head_commit": "abc123",
        "summary": "Helm deployment stack",
        "source_people": [
            {"role": "commit_author", "name": "Jenkins CI", "email": "jenkins@example.com"},
            {"role": "commit_author", "name": f"Alice Example {token}", "email": f"alice{token}@example.com"},
        ],
    }
    repo = await ingest_repository_record(db, project_id=None, record=record)
    assert repo is not None
    assert repo.properties.get("head_commit") == "abc123"

    neighbors = await get_neighbors(db, node_id=repo.id)
    contributors = [n["node"]["display_name"] for n in neighbors if n["edge_type"] == "contributed_to" and n["node"]]
    assert any(token in c for c in contributors)
    assert not any("Jenkins" in c for c in contributors)  # service accounts filtered

    # repo resolvable by short name too
    short = await resolve_node_by_alias(db, project_id=None, alias=f"repo-{token}")
    assert short is not None and short.id == repo.id


@pytest.mark.asyncio
async def test_code_graph_record_ingests_module_internals(db):
    from app.services.knowledge_graph import get_claims_for_node
    from app.services.knowledge_graph.extractors import ingest_code_graph_record

    token = uuid.uuid4().hex[:8]
    repo_name = f"SHOP/svc-{token}"
    record = {
        "repository_name": repo_name,
        "current_head_commit": "abcdef1234567890",
        "stats": {"file_count": 2, "node_count": 9, "edge_count": 12},
        "modules": [
            {
                "path": "dbExport/export.py",
                "name": "export.py",
                "language": "python",
                "symbols": {"class": [f"Exporter{token}"], "function": ["run_export", "main"]},
                "imports": ["dbExport/exporters.py"],
            },
            {
                "path": "dbExport/exporters.py",
                "name": "exporters.py",
                "language": "python",
                "symbols": {"class": ["CsvExporter"]},
                "imports": [],
            },
        ],
    }
    counts = await ingest_code_graph_record(db, project_id=None, record=record)
    assert counts is not None and counts["nodes"] == 3

    module = await resolve_node_by_alias(db, project_id=None, alias="dbExport/export.py")
    assert module is not None and module.node_type == "module"
    # Description carries the code internals a weak answer model reads directly.
    assert f"Exporter{token}" in module.description
    assert "run_export" in module.description
    assert "Imports: dbExport/exporters.py" in module.description
    neighbors = await get_neighbors(db, node_id=module.id)
    assert any(n["edge_type"] == "imports" for n in neighbors)
    assert any(n["edge_type"] == "part_of" for n in neighbors)

    # Re-ingesting the same repo replaces (not duplicates) the code_index claim.
    await ingest_code_graph_record(db, project_id=None, record=record)
    repo = await resolve_node_by_alias(db, project_id=None, alias=repo_name)
    assert repo is not None
    claims = [c for c in await get_claims_for_node(db, node_id=repo.id) if c.claim_type == "code_index"]
    assert len(claims) == 1
    assert "2 code files" in claims[0].statement and "abcdef123456" in claims[0].statement


@pytest.mark.asyncio
async def test_module_nodes_do_not_merge_across_repositories(db):
    token = uuid.uuid4().hex[:8]
    for repo in (f"repo-a-{token}", f"repo-b-{token}"):
        await ingest_code_structure(
            db,
            project_id=None,
            snapshot={"repository": repo, "modules": [{"path": "Dockerfile", "name": "Dockerfile", "imports": []}]},
        )
    from sqlalchemy import select

    from app.models.project.knowledge_graph import KnowledgeGraphNode

    rows = (
        (
            await db.execute(
                select(KnowledgeGraphNode).where(
                    KnowledgeGraphNode.node_type == "module",
                    KnowledgeGraphNode.node_key.in_(
                        [f"mod-repo-a-{token}-dockerfile", f"mod-repo-b-{token}-dockerfile"]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    # Same basename in two repositories must stay two distinct module nodes.
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_release_record_creates_node_claim_and_tracker_link(db):
    from app.services.knowledge_graph import get_claims_for_node
    from app.services.knowledge_graph.extractors import ingest_release_record

    token = uuid.uuid4().hex[:8]
    release = {
        "name": f"rs_{token}",
        "project_key": f"TRK{token.upper()}",
        "released": True,
        "release_date": "2025-08-13",
        "start_date": "2025-07-22",
        "description": "release before device id load",
    }
    node = await ingest_release_record(db, project_id=None, release=release)
    assert node is not None and node.node_type == "release"
    assert "2025-08-13" in node.description and "device id load" in node.description

    claims = [c for c in await get_claims_for_node(db, node_id=node.id) if c.claim_type == "release"]
    assert len(claims) == 1 and "Released on 2025-08-13" in claims[0].statement

    # Re-ingest with updated status supersedes the claim (planned -> released).
    await ingest_release_record(db, project_id=None, release=release)
    claims = [c for c in await get_claims_for_node(db, node_id=node.id) if c.claim_type == "release"]
    assert len(claims) == 1

    tracker = await resolve_node_by_alias(db, project_id=None, alias=f"TRK{token.upper()}")
    assert tracker is not None
    neighbors = await get_neighbors(db, node_id=node.id)
    assert any(
        n["edge_type"] == "part_of" and (n.get("node") or {}).get("id") == tracker.id for n in neighbors
    )
