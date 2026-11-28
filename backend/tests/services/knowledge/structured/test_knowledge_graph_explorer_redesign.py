"""The Workspace graph explorer for the Knowledge-Graph redesign."""

from __future__ import annotations

from app.services.auth import create_access_token
from app.services.knowledge.runtime import get_evidence_runtime
from app.services.knowledge.structured.facts import node_id
from app.services.knowledge.structured.workspace_graph import build_workspace_graph
from tests.services.knowledge.structured.test_structured_graph_surfacing import _full

_SPINE = {"contains", "requires", "supports", "configures", "inconsistent_across", "runs_in", "caused_by",
          "assigned_to_group", "uses_image", "affects_service"}


async def test_totals_are_the_whole_visible_graph_per_store(db):
    _, authorized = await _full(db)
    graph = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized, max_nodes=9)
    stats = graph["stats"]
    structured = stats["totals_by_store"]["structured"]
    assert stats["totals_by_store"]["extracted"] is None
    assert structured["nodes"] > stats["shown_nodes"] and structured["edges"] >= stats["shown_edges"]
    assert (stats["total_nodes"], stats["total_edges"]) == (structured["nodes"], structured["edges"])
    full = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized)
    assert full["stats"]["total_nodes"] >= full["stats"]["shown_nodes"]


async def test_the_overview_samples_every_node_type_not_only_the_spine(db):
    _, authorized = await _full(db)
    graph = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized)
    assert graph["mode"] == "overview" and graph["additive"] is False
    assert {edge["edge_type"] for edge in graph["edges"]} - _SPINE
    for node_type in ("Incident", "Change", "JiraIssue"):
        assert graph["stats"]["node_types"].get(node_type), node_type
    assert len({edge["id"] for edge in graph["edges"]}) == len(graph["edges"])
    small = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized, max_nodes=9)
    assert len(small["nodes"]) <= 9 and set(small["stats"]["layers"]) == {"manual", "configuration", "operations"}


async def test_expand_adds_only_new_neighbours_and_says_it_is_additive(db):
    _, authorized = await _full(db)
    incident = node_id("Incident", "servicenow:INC0000105")
    focus = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                        focus_node_id=incident)
    neighbours = {node["id"] for node in focus["nodes"]} - {incident}
    assert len(neighbours) >= 2
    shown = {incident, sorted(neighbours)[0]}
    grown = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                        expand_node_id=incident, current_node_ids=frozenset(shown))
    assert grown["mode"] == "expand" and grown["additive"] is True and grown["expand_node_id"] == incident
    added = {node["id"] for node in grown["nodes"]}
    assert added == neighbours - shown
    assert all({edge["source"], edge["target"]} <= added | shown for edge in grown["edges"])
    assert all({edge["source"], edge["target"]} & added for edge in grown["edges"])
    one = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                      expand_node_id=incident, current_node_ids=frozenset(shown), max_nodes=1)
    assert len(one["nodes"]) == 1 and one["truncated"]
    done = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                       expand_node_id=incident, current_node_ids=frozenset(neighbours | {incident}))
    assert done["nodes"] == [] and done["state"] == "no_matches"


async def test_expand_http_contract(client, db):
    user, authorized = await _full(db)
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    base = f"/api/v1/workspaces/{authorized.project_id}/knowledge/graph/explorer"
    incident = node_id("Incident", "servicenow:INC0000105")
    response = await client.get(base, headers=headers,
                                params={"expand_node_id": incident, "current_node_ids": incident, "max_nodes": 20})
    body = response.json()
    assert response.status_code == 200 and body["additive"] is True and body["nodes"]
    assert incident not in {node["id"] for node in body["nodes"]}
    both = await client.get(base, headers=headers, params={"expand_node_id": incident, "focus_node_id": incident})
    assert both.status_code == 422
