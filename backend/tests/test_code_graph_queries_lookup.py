"""Native code graph node lookup, filtered search, bounded neighbors, callers, references, shortest-path trace and the project boundary."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models import CodeGraphFile, CodeGraphNode
from app.services.code_intelligence.graph_path_queries import get_code_graph_trace
from app.services.code_intelligence.graph_queries import (
    get_code_graph_neighbors,
    get_code_graph_node,
    get_code_graph_search,
)
from app.services.code_intelligence.graph_relation_queries import (
    get_code_graph_callers,
    get_code_graph_references,
)
from tests.code_graph_queries_support import _seed_code_graph


@pytest.mark.asyncio
async def test_code_graph_node_lookup_reads_native_graph_rows(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_node(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        node_id=seeded["handler_id"],
    )

    assert result["repository"]["id"] == seeded["repository_id"]
    assert result["graph"]["status"] == "completed"
    assert result["graph"]["backend"] == "native"
    assert result["graph_backend"] == "native"
    assert result["graph"]["staleness_state"] == "fresh"
    assert result["node"]["id"] == seeded["handler_id"]
    assert result["node"]["name"] == "handler"
    assert result["node"]["metadata"] == {"visibility": "public"}
    assert result["detail"]["callees"][0]["node"]["name"] == "service"
    assert result["match_count"] == 1


@pytest.mark.asyncio
async def test_code_graph_search_filters_and_downranks_test_generated_vendor_nodes(db):
    seeded = await _seed_code_graph(db)
    generated_file = CodeGraphFile(
        id=str(uuid.uuid4()),
        run_id=seeded["run_id"],
        graph_repository_id=seeded["graph_repository_id"],
        file_path="src/generated/handler.generated.ts",
        language="typescript",
        line_count=4,
        file_metadata={"is_generated": True},
    )
    generated_node = CodeGraphNode(
        id=str(uuid.uuid4()),
        run_id=seeded["run_id"],
        graph_repository_id=seeded["graph_repository_id"],
        source_file_id=generated_file.id,
        external_id="symbol:src/generated/handler.generated.ts:handler",
        node_type="function",
        name="handler",
        language="typescript",
        path="src/generated/handler.generated.ts",
        line_start=1,
        confidence="EXTRACTED",
    )
    db.add_all([generated_file, generated_node])
    await db.commit()

    result = await get_code_graph_search(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="handler",
        limit=10,
    )

    assert result["status"] == "ready"
    result_paths = [item["node"]["path"] for item in result["matches"]]
    assert result_paths[0] == "src/app.py"
    assert result_paths.index("src/generated/handler.generated.ts") > result_paths.index("src/app.py")
    generated_match = next(item for item in result["matches"] if item["node"]["path"] == "src/generated/handler.generated.ts")
    assert generated_match["file_metadata"]["is_generated"] is True

    filtered = await get_code_graph_search(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="handler",
        language="typescript",
        limit=10,
    )
    assert [item["node"]["path"] for item in filtered["matches"]] == ["src/generated/handler.generated.ts"]


@pytest.mark.asyncio
async def test_code_graph_neighbors_traverses_bounded_outgoing_edges(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_neighbors(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="handler",
        relation="calls",
        direction="outgoing",
        depth=1,
        max_nodes=10,
    )

    assert result["status"] == "ready"
    assert result["truncated"] is False
    assert result["start_node"]["id"] == seeded["handler_id"]
    assert {node["id"] for node in result["nodes"]} == {
        seeded["handler_id"],
        seeded["service_id"],
    }
    assert [edge["relation"] for edge in result["edges"]] == ["calls"]
    assert result["limits"] == {"depth": 1, "max_nodes": 10}


@pytest.mark.asyncio
async def test_code_graph_callers_and_references_return_bounded_static_edges(db):
    seeded = await _seed_code_graph(db)

    callers = await get_code_graph_callers(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="service",
        limit=5,
    )
    references = await get_code_graph_references(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="service",
        limit=5,
    )

    assert callers["status"] == "ready"
    assert [node["name"] for node in callers["callers"]] == ["handler"]
    assert callers["edges"][0]["relation"] == "calls"
    assert {node["name"] for node in references["references"]} == {"handler", "test_handler"}
    assert {edge["relation"] for edge in references["edges"]} == {"calls", "tested_by"}


@pytest.mark.asyncio
async def test_code_graph_trace_returns_shortest_path(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_trace(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        source="handler",
        target="test_handler",
        direction="outgoing",
        max_depth=3,
    )

    assert result["status"] == "ready"
    assert [node["name"] for node in result["path"]] == [
        "handler",
        "service",
        "test_handler",
    ]
    assert [edge["relation"] for edge in result["edges"]] == ["calls", "tested_by"]
    assert [hop["node"]["name"] for hop in result["hops"]] == ["handler", "service", "test_handler"]
    assert result["hops"][1]["via_edge"]["relation"] == "calls"
    assert result["hop_count"] == 2


@pytest.mark.asyncio
async def test_code_graph_query_enforces_repository_project_boundary(db):
    seeded = await _seed_code_graph(db)

    with pytest.raises(HTTPException) as exc_info:
        await get_code_graph_node(
            db=db,
            repository_id=seeded["repository_id"],
            project_id=seeded["other_project_id"],
            name="handler",
        )

    assert exc_info.value.status_code == 403
