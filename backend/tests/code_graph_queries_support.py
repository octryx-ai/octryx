"""Shared helpers for the test_code_graph_queries_* modules."""

from __future__ import annotations

import uuid
from typing import Any

from app.models import (
    CodeGraphChunk,
    CodeGraphEdge,
    CodeGraphFile,
    CodeGraphNode,
    CodeGraphRepository,
    CodeGraphRun,
    CodeGraphSymbol,
    CodeRepository,
    Project,
)


def _project(name_prefix: str) -> Project:
    return Project(
        id=str(uuid.uuid4()),
        name=f"{name_prefix}-{uuid.uuid4().hex[:8]}",
        config={},
        is_active=True,
    )


def _code_repository(project_id: str) -> CodeRepository:
    return CodeRepository(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name="native-graph-repo",
        repo_root="/tmp/native-graph-repo",
        provider="local",
        index_backend="ripgrep",
        semantic_backend="regex",
        structure_backend="regex",
        graph_backend="native",
        config_json={"operation_policy": {"read": True}},
        capabilities_json={},
        latest_index_summary={},
        last_index_status="indexed",
    )


def _graph_repository_and_run(repository: CodeRepository) -> tuple[CodeGraphRepository, CodeGraphRun]:
    graph_repository = CodeGraphRepository(
        id=str(uuid.uuid4()),
        code_repository_id=repository.id,
        graph_backend="native",
        graph_schema_version="v1",
        staleness_state="fresh",
    )
    run = CodeGraphRun(
        id=str(uuid.uuid4()),
        graph_repository_id=graph_repository.id,
        code_repository_id=repository.id,
        status="completed",
        trigger="test",
        backend="native",
        file_count=2,
        node_count=4,
        edge_count=2,
        is_stale=False,
    )
    graph_repository.latest_run_id = run.id
    return graph_repository, run


def _graph_files(scope: dict[str, str]) -> tuple[CodeGraphFile, CodeGraphFile]:
    app_file = CodeGraphFile(
        id=str(uuid.uuid4()),
        **scope,
        file_path="src/app.py",
        language="python",
        line_count=20,
    )
    test_file = CodeGraphFile(
        id=str(uuid.uuid4()),
        **scope,
        file_path="tests/test_app.py",
        language="python",
        line_count=12,
        file_metadata={"is_test": True},
    )
    return app_file, test_file


def _app_nodes(scope, app_file) -> tuple[CodeGraphNode, CodeGraphNode, CodeGraphNode]:
    file_node = CodeGraphNode(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=app_file.id,
        external_id="file:src/app.py",
        node_type="file",
        name="src/app.py",
        language="python",
        path="src/app.py",
        confidence="EXTRACTED",
        node_metadata={"kind": "file"},
    )
    handler_node = CodeGraphNode(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=app_file.id,
        external_id="symbol:src/app.py:handler",
        node_type="function",
        name="handler",
        language="python",
        signature="def handler()",
        path="src/app.py",
        line_start=4,
        line_end=8,
        confidence="EXTRACTED",
        node_metadata={"visibility": "public"},
    )
    service_node = CodeGraphNode(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=app_file.id,
        external_id="symbol:src/app.py:service",
        node_type="function",
        name="service",
        language="python",
        signature="def service()",
        path="src/app.py",
        line_start=11,
        line_end=14,
        confidence="EXTRACTED",
    )
    return file_node, handler_node, service_node


def _test_node(scope, test_file) -> CodeGraphNode:
    return CodeGraphNode(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=test_file.id,
        external_id="symbol:tests/test_app.py:test_handler",
        node_type="test",
        name="test_handler",
        language="python",
        path="tests/test_app.py",
        line_start=3,
        line_end=7,
        confidence="EXTRACTED",
    )


def _graph_edges(scope, handler_node, service_node, test_node) -> tuple[CodeGraphEdge, CodeGraphEdge]:
    calls_edge = CodeGraphEdge(
        id=str(uuid.uuid4()),
        **scope,
        source_node_id=handler_node.id,
        target_node_id=service_node.id,
        relation="calls",
        confidence="EXTRACTED",
        edge_metadata={"source": "test"},
    )
    test_edge = CodeGraphEdge(
        id=str(uuid.uuid4()),
        **scope,
        source_node_id=service_node.id,
        target_node_id=test_node.id,
        relation="tested_by",
        confidence="EXTRACTED",
    )
    return calls_edge, test_edge


def _graph_symbols(scope, app_file, test_file, nodes) -> tuple[CodeGraphSymbol, ...]:
    handler_node, service_node, test_node = nodes
    handler_symbol = CodeGraphSymbol(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=app_file.id,
        node_id=handler_node.id,
        stable_symbol_id="symbol:src/app.py:handler",
        kind="function",
        name="handler",
        qualified_name="handler",
        signature="def handler()",
        line_start=4,
        line_end=8,
        confidence="EXTRACTED",
    )
    service_symbol = CodeGraphSymbol(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=app_file.id,
        node_id=service_node.id,
        stable_symbol_id="symbol:src/app.py:service",
        kind="function",
        name="service",
        qualified_name="service",
        signature="def service()",
        line_start=11,
        line_end=14,
        confidence="EXTRACTED",
    )
    test_symbol = CodeGraphSymbol(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=test_file.id,
        node_id=test_node.id,
        stable_symbol_id="symbol:tests/test_app.py:test_handler",
        kind="test",
        name="test_handler",
        qualified_name="test_handler",
        line_start=3,
        line_end=7,
        confidence="EXTRACTED",
    )
    return handler_symbol, service_symbol, test_symbol


def _graph_chunks(scope, app_file, test_file, symbols) -> tuple[CodeGraphChunk, ...]:
    handler_symbol, service_symbol, test_symbol = symbols
    handler_chunk = CodeGraphChunk(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=app_file.id,
        source_symbol_id=handler_symbol.id,
        chunk_kind="symbol",
        path="src/app.py",
        line_start=4,
        line_end=8,
        token_estimate=16,
        content='4: def handler():\n5:     result = service()\n6:     return {"result": result}',
        chunk_metadata={"line_numbered": True},
    )
    service_chunk = CodeGraphChunk(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=app_file.id,
        source_symbol_id=service_symbol.id,
        chunk_kind="symbol",
        path="src/app.py",
        line_start=11,
        line_end=14,
        token_estimate=12,
        content='11: def service():\n12:     return "ok"',
        chunk_metadata={"line_numbered": True},
    )
    test_chunk = CodeGraphChunk(
        id=str(uuid.uuid4()),
        **scope,
        source_file_id=test_file.id,
        source_symbol_id=test_symbol.id,
        chunk_kind="symbol",
        path="tests/test_app.py",
        line_start=3,
        line_end=7,
        token_estimate=14,
        content='3: def test_handler():\n4:     assert handler()["result"] == "ok"',
        chunk_metadata={"line_numbered": True},
    )
    return handler_chunk, service_chunk, test_chunk


async def _seed_code_graph(db) -> dict[str, Any]:
    project = _project("code-graph-project")
    other_project = _project("code-graph-other")
    repository = _code_repository(project.id)
    graph_repository, run = _graph_repository_and_run(repository)
    # Every graph row belongs to the run; symbols and chunks also name the code repository.
    run_scope = {"run_id": run.id, "graph_repository_id": graph_repository.id}
    repository_scope = {**run_scope, "code_repository_id": repository.id}
    app_file, test_file = _graph_files(run_scope)
    file_node, handler_node, service_node = _app_nodes(run_scope, app_file)
    test_node = _test_node(run_scope, test_file)
    calls_edge, test_edge = _graph_edges(run_scope, handler_node, service_node, test_node)
    symbols = _graph_symbols(repository_scope, app_file, test_file, (handler_node, service_node, test_node))
    chunks = _graph_chunks(repository_scope, app_file, test_file, symbols)
    db.add_all([project, other_project, repository, graph_repository, run, app_file, test_file])
    db.add_all([file_node, handler_node, service_node, test_node, calls_edge, test_edge, *symbols, *chunks])
    await db.commit()
    return {
        "project_id": project.id,
        "other_project_id": other_project.id,
        "repository_id": repository.id,
        "handler_id": handler_node.id,
        "service_id": service_node.id,
        "test_id": test_node.id,
        "run_id": run.id,
        "graph_repository_id": graph_repository.id,
    }
