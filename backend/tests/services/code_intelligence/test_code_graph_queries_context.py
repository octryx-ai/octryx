"""Graph statistics, god nodes, affected dependents and budgeted, capped and adaptive context bundles."""

from __future__ import annotations

import pytest

from app.services.code_intelligence.graph_analytics import (
    get_code_graph_affected,
    get_code_graph_god_nodes,
    get_code_graph_stats,
)
from app.services.code_intelligence.graph_context import (
    get_code_graph_context,
)
from tests.code_graph_queries_support import _seed_code_graph


@pytest.mark.asyncio
async def test_code_graph_stats_returns_native_graph_distributions(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_stats(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        limit=3,
    )

    assert result["status"] == "ready"
    assert result["graph_backend"] == "native"
    assert result["stats"]["node_count"] == 4
    assert result["stats"]["edge_count"] == 2
    assert {item["value"]: item["count"] for item in result["node_types"]} == {
        "file": 1,
        "function": 2,
        "test": 1,
    }
    assert {item["value"]: item["count"] for item in result["relations"]} == {
        "calls": 1,
        "tested_by": 1,
    }
    assert result["top_degree_nodes"][0]["node"]["name"] == "service"
    assert result["top_degree_nodes"][0]["degree"] == 2


@pytest.mark.asyncio
async def test_code_graph_god_nodes_ranks_high_degree_nodes(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_god_nodes(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        node_type="function",
        limit=2,
    )

    assert result["status"] == "ready"
    assert result["count"] == 2
    assert [item["node"]["name"] for item in result["nodes"]] == ["service", "handler"]
    assert result["nodes"][0]["incoming_degree"] == 1
    assert result["nodes"][0]["outgoing_degree"] == 1


@pytest.mark.asyncio
async def test_code_graph_affected_defaults_to_incoming_dependents(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_affected(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="service",
        depth=1,
        max_nodes=10,
    )

    assert result["status"] == "ready"
    assert result["start_node"]["id"] == seeded["service_id"]
    assert result["semantics"] == "dependents_that_may_be_affected_by_start_changes"
    assert [node["name"] for node in result["affected_nodes"]] == ["handler"]
    assert result["affected_files"][0]["path"] == "src/app.py"
    assert [edge["relation"] for edge in result["edges"]] == ["calls"]


@pytest.mark.asyncio
async def test_code_graph_context_returns_budgeted_graph_bundle(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_context(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="handler",
        direction="outgoing",
        depth=2,
        max_nodes=10,
        budget_chars=650,
    )

    assert result["graph_backend"] == "native"
    assert result["start_node"]["id"] == seeded["handler_id"]
    assert result["context_nodes"][0]["node"]["name"] == "handler"
    assert result["context_nodes"][0]["selection_reason"] == "start_node"
    assert {item["node"]["name"] for item in result["context_nodes"]} >= {"handler", "service"}
    handler_context = result["context_nodes"][0]
    assert handler_context["source_chunk"]["path"] == "src/app.py"
    assert "4: def handler()" in handler_context["source_chunk"]["content"]
    assert "symbol_match" in handler_context["selection_signals"]
    app_file_context = next(item for item in result["context_files"] if item["path"] == "src/app.py")
    assert {chunk["line_start"] for chunk in app_file_context["source_chunks"]} >= {4, 11}
    assert result["relationship_map"][0]["relation"] == "calls"
    assert result["retrieval_provenance"]["matched_symbols"][0]["name"] == "handler"
    assert result["retrieval_provenance"]["text_matches"]
    assert result["budget"]["requested_chars"] == 650
    assert result["budget"]["used_chars"] <= 650
    assert result["limits"] == {"depth": 2, "max_nodes": 10}


@pytest.mark.asyncio
async def test_code_graph_context_caps_output_and_lists_not_shown_candidates(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_context(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="service",
        direction="both",
        depth=2,
        max_nodes=10,
        budget_chars=500,
    )

    assert result["status"] == "truncated"
    assert result["budget"]["requested_chars"] == 500
    assert result["budget"]["used_chars"] <= 500
    assert result["budget"]["omitted_nodes"] >= 1
    assert result["not_shown_candidates"]
    assert result["not_shown_candidates"][0]["omitted_reason"] == "budget_capped"


@pytest.mark.asyncio
async def test_code_graph_context_uses_adaptive_budget_when_omitted(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_context(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        name="handler",
        direction="both",
        depth=2,
        max_nodes=10,
        budget_chars=0,
    )

    assert result["budget"]["policy"]["mode"] == "adaptive"
    assert result["budget"]["requested_chars"] == 4000
    assert result["budget"]["policy"]["adaptive_default_chars"] == 4000


@pytest.mark.asyncio
async def test_code_graph_context_downranks_test_nodes_when_budget_is_tight(db):
    seeded = await _seed_code_graph(db)

    result = await get_code_graph_context(
        db=db,
        repository_id=seeded["repository_id"],
        project_id=seeded["project_id"],
        query="handler",
        direction="both",
        depth=2,
        max_nodes=10,
        budget_chars=650,
    )

    selected_names = [item["node"]["name"] for item in result["context_nodes"]]
    assert selected_names[:2] == ["handler", "service"]
    omitted_names = [item["node"]["name"] for item in result["not_shown_candidates"]]
    assert "test_handler" in omitted_names
    omitted_test = next(item for item in result["not_shown_candidates"] if item["node"]["name"] == "test_handler")
    assert "test_downranked" in omitted_test["selection_signals"]
