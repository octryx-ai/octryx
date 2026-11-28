"""Route-aware graph traces and endpoint context from a seeded FastAPI route to its handler and downstream service."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.models import CodeGraphEdge, CodeGraphFile, CodeGraphNode, CodeGraphRoute
from app.services.code_intelligence.graph_context import (
    get_code_graph_context,
)
from app.services.code_intelligence.graph_path_queries import get_code_graph_trace
from tests.code_graph_queries_support import _seed_code_graph


async def _add_fastapi_route_to_seed(db, seeded: dict[str, Any]) -> str:
    app_file = (
        await db.execute(
            select(CodeGraphFile).where(
                CodeGraphFile.run_id == seeded["run_id"],
                CodeGraphFile.file_path == "src/app.py",
            )
        )
    ).scalar_one()
    route_node = CodeGraphNode(
        id=str(uuid.uuid4()),
        run_id=seeded["run_id"],
        graph_repository_id=seeded["graph_repository_id"],
        source_file_id=app_file.id,
        external_id="route:fastapi:GET:/health:src/app.py:2",
        node_type="route",
        name="GET /health",
        language="route",
        signature="GET /health",
        path="src/app.py",
        line_start=2,
        line_end=2,
        confidence="EXTRACTED",
        node_metadata={"framework": "fastapi", "method": "GET", "route_path": "/health"},
    )
    route_edge = CodeGraphEdge(
        id=str(uuid.uuid4()),
        run_id=seeded["run_id"],
        graph_repository_id=seeded["graph_repository_id"],
        source_node_id=route_node.id,
        target_node_id=seeded["handler_id"],
        relation="routes_to",
        confidence="EXTRACTED",
    )
    route_row = CodeGraphRoute(
        id=str(uuid.uuid4()),
        run_id=seeded["run_id"],
        graph_repository_id=seeded["graph_repository_id"],
        code_repository_id=seeded["repository_id"],
        router_file_id=app_file.id,
        route_node_id=route_node.id,
        method="GET",
        route_path="/health",
        framework="fastapi",
        line_start=2,
        line_end=2,
        confidence="EXTRACTED",
        route_metadata={"framework": "fastapi", "method": "GET", "route_path": "/health"},
    )
    db.add_all([route_node, route_edge, route_row])
    await db.commit()
    return route_node.id


@pytest.mark.asyncio
async def test_code_graph_trace_resolves_route_path_to_downstream_service(db):
    seeded = await _seed_code_graph(db)
    await _add_fastapi_route_to_seed(db, seeded)

    result = await get_code_graph_trace(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        source="/health",
        target="service",
        direction="outgoing",
        max_depth=3,
    )

    assert result["status"] == "ready"
    assert [node["name"] for node in result["path"]] == ["GET /health", "handler", "service"]
    assert [edge["relation"] for edge in result["edges"]] == ["routes_to", "calls"]
    assert result["no_path_reason"] == ""


@pytest.mark.asyncio
async def test_code_graph_trace_reports_static_gap_from_route_without_hallucinated_edge(db):
    seeded = await _seed_code_graph(db)
    await _add_fastapi_route_to_seed(db, seeded)
    dynamic_node = CodeGraphNode(
        id=str(uuid.uuid4()),
        run_id=seeded["run_id"],
        graph_repository_id=seeded["graph_repository_id"],
        external_id="symbol:src/dynamic.py:dynamicSink",
        node_type="function",
        name="dynamicSink",
        language="python",
        signature="def dynamicSink()",
        path="src/dynamic.py",
        line_start=1,
        confidence="INFERRED",
    )
    db.add(dynamic_node)
    await db.commit()

    result = await get_code_graph_trace(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        source="/health",
        target="dynamicSink",
        direction="outgoing",
        max_depth=3,
    )

    assert result["status"] == "no_path"
    assert result["source_node"]["name"] == "GET /health"
    assert result["target_node"]["name"] == "dynamicSink"
    assert result["path"] == []
    assert "dynamic-dispatch" in result["no_path_reason"]


@pytest.mark.asyncio
async def test_code_graph_context_for_endpoint_includes_route_handler_and_service(db):
    seeded = await _seed_code_graph(db)
    await _add_fastapi_route_to_seed(db, seeded)

    result = await get_code_graph_context(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="/health",
        direction="outgoing",
        depth=2,
        max_nodes=10,
        budget_chars=2000,
    )

    assert result["status"] == "ready"
    assert result["start_node"]["name"] == "GET /health"
    assert [item["node"]["name"] for item in result["context_nodes"]][:3] == ["GET /health", "handler", "service"]
    assert {item["relation"] for item in result["relationship_map"]} == {"routes_to", "calls"}
    app_context = next(item for item in result["context_files"] if item["path"] == "src/app.py")
    assert {chunk["line_start"] for chunk in app_context["source_chunks"]} >= {4, 11}
    assert result["retrieval_provenance"]["selection_signals"]["route_relevance"] >= 1
