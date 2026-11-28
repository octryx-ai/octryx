"""Native code graph indexing of routes, calls and status, and graphify artifacts."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import (
    CodeGraphChunk,
    CodeGraphEdge,
    CodeGraphNode,
    CodeGraphReference,
    CodeGraphRoute,
    CodeGraphRun,
    CodeGraphSnapshot,
    CodeGraphStaleness,
    CodeGraphSymbol,
    Project,
)
from app.services.code_intelligence.graph_path_queries import get_code_graph_files, get_code_graph_trace
from app.services.code_intelligence.graph_queries import get_code_graph_callees, get_code_graph_status
from app.services.code_intelligence.indexing import (
    run_code_index,
)
from app.services.code_intelligence.queries import (
    find_symbol_definition,
    get_graph_summary,
    search_repository_code,
)
from app.services.code_intelligence.repository import (
    create_code_repository,
)
from tests.services.code_intelligence.code_intelligence_service_support import _write_repo_fixture


async def _seed_native_repository(db, tmp_path):
    project = Project(
        id=str(uuid.uuid4()),
        name="native-code-graph-project",
        description="test project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "native-workspace"
    _write_repo_fixture(repo_root)

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "native-workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "code_graph",
        },
    )
    return project, repo_root, created


async def _latest_graph_run(db, repository_id):
    return (
        await db.execute(
            select(CodeGraphRun)
            .where(CodeGraphRun.code_repository_id == repository_id)
            .order_by(CodeGraphRun.started_at.desc())
        )
    ).scalars().first()


async def _assert_graph_rows(db, run):
    nodes = (await db.execute(select(CodeGraphNode).where(CodeGraphNode.run_id == run.id))).scalars().all()
    edges = (await db.execute(select(CodeGraphEdge).where(CodeGraphEdge.run_id == run.id))).scalars().all()
    symbols = (await db.execute(select(CodeGraphSymbol).where(CodeGraphSymbol.run_id == run.id))).scalars().all()
    references = (await db.execute(select(CodeGraphReference).where(CodeGraphReference.run_id == run.id))).scalars().all()
    routes = (await db.execute(select(CodeGraphRoute).where(CodeGraphRoute.run_id == run.id))).scalars().all()
    chunks = (await db.execute(select(CodeGraphChunk).where(CodeGraphChunk.run_id == run.id))).scalars().all()
    snapshots = (await db.execute(select(CodeGraphSnapshot).where(CodeGraphSnapshot.run_id == run.id))).scalars().all()
    staleness = (await db.execute(select(CodeGraphStaleness).where(CodeGraphStaleness.run_id == run.id))).scalars().all()
    node_types = {node.node_type for node in nodes}
    relations = {edge.relation for edge in edges}

    assert "route" in node_types
    assert "function" in node_types
    assert {"defines", "calls", "imports", "routes_to"} <= relations
    assert any(node.node_metadata.get("qualified_name") == "Greeter.hello" for node in nodes)
    assert any(node.node_metadata.get("framework") == "fastapi" for node in nodes)
    assert any(node.node_metadata.get("framework") == "spring" for node in nodes)
    assert any(symbol.qualified_name == "Greeter.hello" for symbol in symbols)
    assert any(reference.reference_kind == "calls" and reference.status == "resolved" for reference in references)
    assert any(reference.status == "unresolved" for reference in references)
    assert {route.framework for route in routes} >= {"fastapi", "spring"}
    assert any(chunk.chunk_kind == "file" and chunk.content for chunk in chunks)
    assert any(chunk.chunk_kind == "symbol" and chunk.content for chunk in chunks)
    assert len(snapshots) == 1
    assert {item.status for item in staleness} == {"fresh"}
    # The code-graph summary is no longer copied into the retired KnowledgeMap.
    assert "knowledge_summary" not in (run.run_metadata or {})


async def _assert_trace_definitions_and_search(db, repository_id, repo_root, project_id):
    trace = await get_code_graph_trace(
        db=db,
        repository_id=repository_id,
        cwd=repo_root,
        project_id=project_id,
        source="GET /hello",
        target="helper",
        direction="outgoing",
        max_depth=3,
        include_source=True,
    )
    assert trace["status"] == "ready"
    assert [item["relation"] for item in trace["edges"]] == ["routes_to", "calls"]
    assert [hop["node"]["name"] for hop in trace["hops"]] == ["GET /hello", "hello_route", "helper"]
    assert trace["hops"][-1]["source_chunk"]["path"] == "src/app.py"

    definitions = await find_symbol_definition(
        db=db,
        repository_id=repository_id,
        cwd=repo_root,
        project_id=project_id,
        symbol="helper",
    )
    assert definitions["resolution_backend"] == "native_graph+fallback"
    assert definitions["native_graph"]["used"] is True
    assert definitions["definitions"][0]["backend"] == "native_graph"

    search_result = await search_repository_code(
        db=db,
        repository_id=repository_id,
        cwd=repo_root,
        project_id=project_id,
        query="renderGreeting",
        limit=20,
    )
    assert search_result["resolution_backend"] == "native_graph+text"
    assert search_result["native_graph"]["used"] is True


@pytest.mark.asyncio
async def test_native_code_graph_indexing_extracts_routes_calls_and_status(db, tmp_path: Path):
    project, repo_root, created = await _seed_native_repository(db, tmp_path)

    indexed = await run_code_index(db, repository_id=created["id"], force=True, trigger="test")

    assert indexed["snapshot"]["artifacts"]["code_graph"]["status"] == "ready"
    assert indexed["snapshot"]["artifacts"]["code_graph"]["unresolved_reference_count"] >= 1

    run = await _latest_graph_run(db, created["id"])
    assert run is not None
    assert run.status == "ready"
    assert run.node_count >= 10
    assert run.edge_count >= 8
    assert run.unresolved_reference_count >= 1

    await _assert_graph_rows(db, run)

    status = await get_code_graph_status(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
    )
    assert status["status"] == "fresh"
    assert status["latest_run"]["node_count"] == run.node_count
    assert status["latest_run"]["unresolved_reference_count"] == run.unresolved_reference_count

    files = await get_code_graph_files(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
        language="python",
    )
    assert files["status"] == "ready"
    assert {item["path"] for item in files["files"]} >= {"src/app.py", "src/usage.py"}

    callees = await get_code_graph_callees(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
        query="hello_route",
    )
    assert callees["semantics"] == "direct_static_callees_from_start_node"
    assert any(item["name"] == "helper" for item in callees["callees"])

    await _assert_trace_definitions_and_search(db, created["id"], repo_root, project.id)


@pytest.mark.asyncio
async def test_graphify_artifacts_are_built_and_summarized(db, tmp_path: Path):
    project = Project(
        id=str(uuid.uuid4()),
        name="code-intel-graph-project",
        description="graph project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "graph-workspace"
    _write_repo_fixture(repo_root)

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "graph-workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "graphify",
        },
    )
    indexed = await run_code_index(db, repository_id=created["id"], force=True, trigger="test")
    graph_artifact = (indexed["snapshot"].get("artifacts") or {}).get("graphify") or {}
    assert graph_artifact.get("status") == "ready"
    assert int(graph_artifact.get("node_count") or 0) >= indexed["snapshot"]["file_count"]
    assert Path(str(graph_artifact.get("graph_path"))).exists()
    assert Path(str(graph_artifact.get("report_path"))).exists()

    summary = await get_graph_summary(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
    )
    assert summary["graph_status"] == "ready"
    assert summary["backend"] in {"internal", "external_graphify"}
    assert summary["node_count"] >= indexed["snapshot"]["file_count"]
    assert "Graph" in summary["report_excerpt"]
