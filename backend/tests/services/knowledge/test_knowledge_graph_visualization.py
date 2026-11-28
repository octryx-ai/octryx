"""The current graph explorer reads the Workspace graph's facts, gated by real source evidence ACLs."""

from __future__ import annotations

import dataclasses

import pytest

from app.models.project.knowledge_evidence import KnowledgeSourceRevision
from app.services.auth import create_access_token
from app.services.knowledge.temporal import visualization as view
from app.services.knowledge.temporal.errors import GraphStoreError, GraphStoreState
from app.services.knowledge.temporal.visualization_queries import COUNT_QUERY, FACTS_QUERY, MAX_CANDIDATES
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.services.knowledge.access.test_knowledge_graph_expansion import FACTS, _library


class ExplorerGraph:
    def __init__(self, facts=FACTS, failure=None):
        self.facts, self.failure = facts, failure
        self.calls = []
        self.closed = False

    async def execute_query(self, statement, **params):
        self.calls.append((statement, params))
        if self.failure:
            raise self.failure
        if statement == COUNT_QUERY:
            visible = [fact for fact in self.facts if set(fact["episodes"]) & set(params["episodes"])]
            ends = {fact[key] for fact in visible for key in ("source_uuid", "target_uuid")}
            return [{"nodes": len(ends), "edges": len(visible)}], None, None
        assert statement == FACTS_QUERY
        rows = [dict(fact) for fact in self.facts if set(fact["episodes"]) & set(params["episodes"])]
        if params["focus"]:
            rows = [r for r in rows if params["focus"] in (r["source_uuid"], r["target_uuid"])]
        if params["query"]:
            rows = [r for r in rows if any(params["query"] in r[k].lower() for k in ("source", "target", "fact"))]
        return rows[:params["limit"]], None, None

    async def close(self):
        self.closed = True


def install(monkeypatch, graph):
    monkeypatch.setattr(view, "PostgresGraphDriver", lambda project_id: graph)


async def test_current_graph_search_focus_and_exact_citations(db, monkeypatch):
    runtime, _, authorized, _ = await _library(db)
    graph = ExplorerGraph()
    install(monkeypatch, graph)
    result = await view.build_current_graph(db, runtime=runtime, authorized=authorized, query="Java 17")
    assert result["state"] == "ok" and result["store"] == "extracted_graph"
    assert {node["id"] for node in result["nodes"]} == {"n-sb4", "n-java"}
    assert result["edges"][0]["id"] == "f-java"
    assert result["edges"][0]["evidence_key"]
    assert result["edges"][0]["source_id"] and result["edges"][0]["revision_id"]
    assert result["edges"][0]["source_url"] == "https://example.com/sb4-migration"
    # Totals are the whole visible window (every readable fact), not the two-node search page.
    assert result["stats"]["total_edges"] == 5 and result["stats"]["total_nodes"] > len(result["nodes"])
    assert result["stats"]["counts_scope"] == "visible"
    assert graph.closed
    detail = await view.current_graph_node(db, runtime=runtime, authorized=authorized, node_id="n-java")
    assert detail["claims"][0]["evidence_key"] == result["edges"][0]["evidence_key"]
    assert detail["properties"] == {} and detail["description"] == ""
    assert detail["relations"][0]["peer_id"] == "n-sb4"
    assert await view.current_graph_node(db, runtime=runtime, authorized=authorized, node_id="n-gw") is None


async def test_restricted_stale_and_foreign_facts_never_emit_nodes_or_counts(db, monkeypatch):
    runtime, _, authorized, _ = await _library(db)
    graph = ExplorerGraph()
    install(monkeypatch, graph)
    result = await view.build_current_graph(db, runtime=runtime, authorized=authorized)
    assert {edge["id"] for edge in result["edges"]} == {"f-java", "f-jakarta", "f-fw7", "f-banner", "f-json"}
    assert "n-gw" not in {node["id"] for node in result["nodes"]}
    assert "ep-internal" not in graph.calls[0][1]["episodes"]
    revision = await db.get(KnowledgeSourceRevision, result["edges"][0]["revision_id"])
    revision.state = "superseded"
    await db.flush()
    stale = await view.build_current_graph(db, runtime=runtime, authorized=authorized)
    assert "f-java" not in {edge["id"] for edge in stale["edges"]}
    foreign = dataclasses.replace(authorized, project_id="different-workspace")
    assert (await view.build_current_graph(db, runtime=runtime, authorized=foreign))["state"] == "not_extracted"


@pytest.mark.parametrize("failure,state", [
    (GraphStoreError(GraphStoreState.UNAVAILABLE), "unavailable"),
    (GraphStoreError(GraphStoreState.UNAUTHORIZED), "unauthorized"),
    (TimeoutError(), "timeout"),
])
async def test_errors_are_not_empty_success(db, monkeypatch, failure, state):
    runtime, _, authorized, _ = await _library(db)
    graph = ExplorerGraph(failure=failure)
    install(monkeypatch, graph)
    result = await view.build_current_graph(db, runtime=runtime, authorized=authorized)
    assert result["state"] == state and result["stats"]["total_edges"] is None
    assert result["nodes"] == [] and graph.closed


async def test_bounds_and_empty_search(db, monkeypatch):
    runtime, _, authorized, _ = await _library(db)
    graph = ExplorerGraph()
    install(monkeypatch, graph)
    bounded = await view.build_current_graph(db, runtime=runtime, authorized=authorized, max_nodes=2)
    assert len(bounded["nodes"]) <= 2 and bounded["truncated"]
    assert graph.calls[0][1]["limit"] == MAX_CANDIDATES + 1
    none = await view.build_current_graph(db, runtime=runtime, authorized=authorized, query="Nonexistent topic")
    assert none["state"] == "no_matches" and none["match_ids"] == []


async def test_http_workspace_auth_and_node_sources(client, db, monkeypatch):
    _, user, authorized, _ = await _library(db)
    graph = ExplorerGraph()
    install(monkeypatch, graph)
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    base = f"/api/v1/workspaces/{authorized.project_id}/knowledge/graph/explorer"
    assert (await client.get(base)).status_code == 401
    result = await client.get(base, headers=headers, params={"query": "Java 17"})
    assert result.status_code == 200 and result.json()["edges"][0]["id"] == "f-java"
    detail = await client.get(base + "/nodes/n-java", headers=headers)
    assert detail.status_code == 200 and detail.json()["claims"][0]["source_id"]
    denied = await client.get(base + "/nodes/n-gw", headers=headers)
    assert denied.status_code == 404
    unknown = await client.get("/api/v1/workspaces/not-a-workspace/knowledge/graph/explorer", headers=headers)
    assert unknown.status_code == 404
    other = await seed_workspace(db, name="Unauthorized explorer workspace")
    foreign = await client.get(f"/api/v1/workspaces/{other}/knowledge/graph/explorer", headers=headers)
    assert foreign.status_code == 404
    assert {k: v for k, v in foreign.json().items() if k != "request_id"} == {
        k: v for k, v in unknown.json().items() if k != "request_id"
    }
    assert (await client.get(base, headers=headers, params={"max_nodes": 5000})).status_code == 422
