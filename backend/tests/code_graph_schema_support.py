"""Seeds one row in every code graph table for the test_code_graph_schema uniqueness and cascade test."""

from __future__ import annotations

import uuid

from app.models import (
    CodeGraphChunk,
    CodeGraphEdge,
    CodeGraphFile,
    CodeGraphNode,
    CodeGraphReference,
    CodeGraphRepository,
    CodeGraphRoute,
    CodeGraphRun,
    CodeGraphSnapshot,
    CodeGraphStaleness,
    CodeGraphSymbol,
    CodeRepository,
    Project,
)


def _repository_rows():
    """Project, code repository, graph repository and a ready run pointing at each other."""
    project = Project(
        id=str(uuid.uuid4()),
        name="code-graph-schema-project",
        config={},
        is_active=True,
    )
    repository = CodeRepository(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="schema-repo",
        repo_root="/tmp/schema-repo",
        provider="local",
        graph_backend="code_graph",
        config_json={"operation_policy": {"read": True, "index": True}},
    )
    graph_repository = CodeGraphRepository(
        id=str(uuid.uuid4()),
        code_repository_id=repository.id,
        graph_backend="code_graph",
        graph_schema_version="v1",
        staleness_state="fresh",
    )
    run = CodeGraphRun(
        id=str(uuid.uuid4()),
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        status="ready",
        trigger="test",
        backend="code_graph",
        file_count=1,
        node_count=2,
        edge_count=1,
    )
    graph_repository.latest_run_id = run.id
    return project, repository, graph_repository, run


def _file_and_node_rows(graph_repository, run):
    graph_file = CodeGraphFile(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        file_path="src/app.py",
        language="python",
        file_hash="hash-a",
        line_count=10,
    )
    source_node = CodeGraphNode(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        source_file_id=graph_file.id,
        external_id="symbol:src/app.py:handler:1",
        node_type="function",
        name="handler",
        language="python",
        path="src/app.py",
        line_start=1,
        line_end=3,
    )
    target_node = CodeGraphNode(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        source_file_id=graph_file.id,
        external_id="symbol:src/app.py:service:5",
        node_type="function",
        name="service",
        language="python",
        path="src/app.py",
        line_start=5,
        line_end=8,
    )
    return graph_file, source_node, target_node


def _symbol_rows(repository, graph_repository, run, graph_file, source_node, target_node):
    source_symbol = CodeGraphSymbol(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        source_file_id=graph_file.id,
        node_id=source_node.id,
        stable_symbol_id=source_node.external_id,
        kind="function",
        name="handler",
        qualified_name="handler",
        line_start=1,
        line_end=3,
        extraction_backend="python_ast",
    )
    target_symbol = CodeGraphSymbol(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        source_file_id=graph_file.id,
        node_id=target_node.id,
        stable_symbol_id=target_node.external_id,
        kind="function",
        name="service",
        qualified_name="service",
        line_start=5,
        line_end=8,
        extraction_backend="python_ast",
    )
    return source_symbol, target_symbol


def _link_rows(repository, graph_repository, run, graph_file, source_node, target_node, source_symbol, target_symbol):
    """Call edge, resolved reference, route and symbol chunk between the two seeded functions."""
    edge = CodeGraphEdge(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        source_node_id=source_node.id,
        target_node_id=target_node.id,
        relation="calls",
        confidence="EXTRACTED",
    )
    reference = CodeGraphReference(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        source_file_id=graph_file.id,
        source_symbol_id=source_symbol.id,
        target_symbol_id=target_symbol.id,
        edge_id=edge.id,
        reference_name="service",
        reference_kind="calls",
        status="resolved",
        line_start=2,
    )
    route = CodeGraphRoute(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        router_file_id=graph_file.id,
        route_node_id=source_node.id,
        handler_symbol_id=source_symbol.id,
        method="GET",
        route_path="/health",
        framework="fastapi",
    )
    chunk = CodeGraphChunk(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        source_file_id=graph_file.id,
        source_symbol_id=source_symbol.id,
        chunk_kind="symbol",
        path="src/app.py",
        line_start=1,
        line_end=3,
        token_estimate=8,
        content="1: def handler():\n2:     return service()",
        content_hash="chunk-hash",
    )
    return edge, reference, route, chunk


def _snapshot_rows(repository, graph_repository, run):
    snapshot = CodeGraphSnapshot(
        id=str(uuid.uuid4()),
        run_id=run.id,
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        snapshot_kind="index",
        content_hash="snapshot-hash",
        file_count=1,
        symbol_count=2,
        edge_count=1,
    )
    staleness = CodeGraphStaleness(
        id=str(uuid.uuid4()),
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        run_id=run.id,
        file_path="src/app.py",
        observed_hash="hash-a",
        indexed_hash="hash-a",
        status="fresh",
    )
    return snapshot, staleness


async def _seed_full_code_graph_schema(db) -> dict[str, str]:
    project, repository, graph_repository, run = _repository_rows()
    graph_file, source_node, target_node = _file_and_node_rows(graph_repository, run)
    source_symbol, target_symbol = _symbol_rows(repository, graph_repository, run, graph_file, source_node, target_node)
    file_rows = (graph_file, source_node, target_node, source_symbol, target_symbol)
    edge, reference, route, chunk = _link_rows(repository, graph_repository, run, *file_rows)
    snapshot, staleness = _snapshot_rows(repository, graph_repository, run)
    db.add_all(
        [
            project,
            repository,
            graph_repository,
            run,
            graph_file,
            source_node,
            target_node,
            source_symbol,
            target_symbol,
            edge,
            reference,
            route,
            chunk,
            snapshot,
            staleness,
        ]
    )
    await db.commit()
    return {
        "graph_repository_id": graph_repository.id,
        "run_id": run.id,
        "source_symbol_stable_id": source_symbol.stable_symbol_id,
    }
