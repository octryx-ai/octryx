"""D: the structured graph in the explorer, in search, on MCP, and in the admin endpoints.

The three root acceptance questions are answered from one fixture Workspace (Server manual, three
app.ini components, ServiceNow and Jira records, a Jira connector):

1. "Welche Changes betrafen den Service Checkout vor INC0000105?" → ``ops_chain(ticket=INC0000105)``;
2. "Welche Jira-Tickets hängen an CHG0000202?" → ``ops_chain(ticket=CHG0000202)``;
3. "Welche Konfiguration betrifft RequestTimeout …?" → ``config_vs_manual(parameter=RequestTimeout)`` and
   ``ops_chain(ticket=ACME-117)`` (the settings whose comment names the ticket).
"""

from __future__ import annotations

import re

from sqlalchemy import select

from app.models.project.knowledge_source_acl import KnowledgeSourceAcl
from app.models.project.knowledge_structured import KnowledgeStructuredBuild
from app.services.auth import create_access_token
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.runtime import get_evidence_runtime
from app.services.knowledge.structured.build import claim_next_build, refresh_after_sync, request_build
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.facts import node_id
from app.services.knowledge.structured.workspace_graph import build_workspace_graph
from app.services.mcp_governed_knowledge import McpCaller, run_governed_mcp_tool
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from tests.knowledge_evidence_seed_support import seed_workspace, tool_context
from tests.knowledge_evidence_text_support import unfenced
from tests.test_structured_graph_operations import CHANGE, INCIDENT, INVENTORY, ISSUE
from tests.test_structured_graph_report import _workspace

LATER_CHANGE = re.sub(r"(?m)^- Opened: .*$", "- Opened: 2026-01-05 09:00:00",
                      CHANGE.replace("CHG0000202", "CHG0000300"))
LATER_CHANGE = re.sub(r"(?m)^- Closed: .*$", "- Closed: 2026-01-06 18:00:00", LATER_CHANGE)
OTHER_SERVICE = CHANGE.replace("CHG0000202", "CHG0000150").replace("Business service: Checkout",
                                                                   "Business service: Payments")


async def _full(db):
    user, authorized, revisions, _ = await _workspace(db, jira=True)
    runtime = get_evidence_runtime()
    for key, title, text in (
        ("servicenow.sn.inc", "INC0000105", INCIDENT), ("servicenow.sn.chg", "CHG0000202", CHANGE),
        ("servicenow.sn.later", "CHG0000300", LATER_CHANGE), ("servicenow.sn.other", "CHG0000150", OTHER_SERVICE),
        ("jira.jira-shop.117", "ACME-117", ISSUE),
        ("kubernetes.k8s-shop.acme-orders-test-euc1", "Kubernetes inventory: acme-orders-test-euc1", INVENTORY),
    ):
        await ingest_text_source(db, runtime=runtime, authorized=authorized, source_key=key, display_title=title,
                                 declared_media_type="text/markdown", data=text.encode(), created_by=user.id)
    while await EvidenceProjector(runtime).project_once(db, worker_id="test") is not None:
        pass
    build = await request_build(db, project_id=authorized.project_id, layers=["operations"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    assert await run_build_slice(db, runtime=runtime, build_id=build.id, worker_id="w") == "completed"
    return user, authorized


def _caller(user_id: str, workspace_id: str) -> McpCaller:
    return McpCaller(user_id=user_id, grant_id="grant-structured", scopes=("knowledge:read",),
                     workspace_header=workspace_id, client_name="claude-code")


async def _mcp(db, user, authorized, tool, **arguments):
    return await run_governed_mcp_tool(db, caller=_caller(user.id, authorized.project_id), tool_name=tool,
                                       arguments=arguments)


async def test_question_1_changes_of_the_service_before_the_incident(db):
    user, authorized = await _full(db)
    chain = await _mcp(db, user, authorized, "ops_chain", ticket="INC0000105")
    # Through the MCP the result is fenced (knowledge_fence): content_is_data is the notice naming the fence.
    assert chain["state"] == "ok" and chain["content_is_data"].startswith("Untrusted data from the Knowledge sources")
    chain = unfenced(chain)
    prior = chain["prior_changes"]
    assert prior["basis"] == "same_service" and prior["anchor"] == ["Checkout"]
    assert [item["label"].split()[0] for item in prior["changes"]] == ["CHG0000202"]  # not the later one
    cause = next(fact for fact in chain["facts"] if fact["relation"] == "caused_by")
    assert cause["target"].startswith("CHG0000202") and cause["citations"][0]["cite_as"].startswith("INC0000105 § Description")


async def test_question_2_jira_issues_hanging_on_a_change(db):
    user, authorized = await _full(db)
    chain = await _mcp(db, user, authorized, "ops_chain", ticket="CHG0000202")
    jira = {(fact["relation"], fact["source"].split()[0], fact["target"].split()[0]) for fact in chain["facts"]}
    assert ("mentions", "ACME-117", "CHG0000202") in jira  # the issue names the change
    assert ("mentions", "CHG0000202", "ACME-117") in jira  # and the change names the issue


async def test_question_3_configuration_of_requesttimeout_and_its_ticket(db):
    user, authorized = await _full(db)
    report = await _mcp(db, user, authorized, "config_vs_manual", parameter="RequestTimeout")
    sections = [item for item in report["unknown_section"] if item["section"] == "QueueConnection"]
    assert {item["component"] for item in sections} == {"conf", "data", "worker"}
    assert all("RequestTimeout" in item["keys"] for item in sections)
    conf = next(item for item in sections if item["component"] == "conf")  # the order follows the source names
    assert conf["name_matches"][0]["parameter"] == "[Cache?] RequestTimeout"
    chain = await _mcp(db, user, authorized, "ops_chain", ticket="ACME-117")
    settings = {(fact["source"], fact["citations"][0]["line"]) for fact in chain["configuration"]}
    assert ("[QueueConnection] RequestTimeout", 28) in settings
    neighbors = await _mcp(db, user, authorized, "graph_neighbors", entity="RequestTimeout")
    assert {node["type"] for node in neighbors["nodes"]} >= {"Parameter", "ConfiguredSetting"}
    assert "not_shown" not in neighbors
    assert any(fact["relation"] == "inconsistent_across" for fact in neighbors["facts"])


async def test_tools_refuse_empty_requests_and_say_not_found(db):
    user, authorized = await _full(db)
    assert (await _mcp(db, user, authorized, "config_vs_manual"))["state"] == "invalid_request"
    assert (await _mcp(db, user, authorized, "ops_chain"))["state"] == "invalid_request"
    assert (await _mcp(db, user, authorized, "graph_neighbors", entity="NoSuchThing"))["state"] == "not_found"
    overview = await _mcp(db, user, authorized, "config_vs_manual", overview=True)
    assert overview["state"] == "ok" and overview["counts"]["unknown_section"] >= 3


async def test_the_explorer_shows_every_layer_with_citations_and_filters_layers(db):
    user, authorized = await _full(db)
    graph = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized)
    assert graph["store"] == "workspace_graph" and graph["state"] == "ok"
    assert set(graph["stats"]["layers"]) == {"manual", "configuration", "operations"}
    small = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized, max_nodes=9)
    assert set(small["stats"]["layers"]) == {"manual", "configuration", "operations"}  # every layer, bounded
    assert graph["layer_states"]["extracted"] == "not_extracted"  # nothing extracted here
    assert all(edge["citations"] and edge["cite_as"] for edge in graph["edges"])
    only_ops = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                           layers=("operations",))
    assert {node["layer"] for node in only_ops["nodes"]} == {"operations"}
    found = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                        query="requesttimeout")
    assert found["match_ids"] and all(node["layer"] != "extracted" for node in found["nodes"])


async def test_the_explorer_node_detail_and_http_contract(client, db):
    user, authorized = await _full(db)
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    base = f"/api/v1/workspaces/{authorized.project_id}/knowledge/graph/explorer"
    response = await client.get(base, headers=headers, params={"query": "INC0000105", "layers": "operations"})
    assert response.status_code == 200 and response.json()["store"] == "workspace_graph"
    assert (await client.get(base, headers=headers, params={"layers": "everything"})).status_code == 422
    incident = node_id("Incident", "servicenow:INC0000105")
    detail = await client.get(f"{base}/nodes/{incident}", headers=headers)
    body = detail.json()
    assert detail.status_code == 200 and body["status"] == "deterministic" and body["properties"]["state"]
    assert {relation["edge_type"] for relation in body["relations"]} >= {"caused_by", "assigned_to_group"}
    assert (await client.get(f"{base}/nodes/{'0' * 64}", headers=headers)).status_code == 404


async def test_a_restricted_source_disappears_from_explorer_and_tools(db):
    user, authorized = await _full(db)
    db.add(KnowledgeSourceAcl(project_id=authorized.project_id, source_key="servicenow.sn.inc",
                              restriction="restricted"))
    await db.commit()
    chain = await _mcp(db, user, authorized, "ops_chain", ticket="INC0000105")
    assert chain["state"] == "not_found" or all(not record["label"].startswith("INC0000105 Null")
                                                for record in chain["records"])
    graph = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                        query="inc0000105")
    assert not any(edge["edge_type"] == "caused_by" for edge in graph["edges"])


async def test_search_hits_carry_structured_one_hop_facts(db):
    user, authorized = await _full(db)
    context = tool_context(user_id=user.id, project_id=authorized.project_id, project_ids=[authorized.project_id],
                           db=db)
    found = await KnowledgeSearchTool().execute({"query": "Empty quotes from the pricing service"}, context)
    assert found["state"] == "ok"
    facts = found["facts"]
    assert facts["state"] == "ok" and facts["facts"]
    kinds = {item["kind"] for item in facts["facts"]}
    assert kinds & {"CAUSED_BY", "ASSIGNED_TO_GROUP", "AFFECTS_SERVICE"}


async def test_build_and_status_endpoints_and_sync_refresh(client, db):
    user, authorized = await _full(db)
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    base = f"/api/v1/workspaces/{authorized.project_id}/knowledge/graph/structured"
    status = (await client.get(base, headers=headers)).json()
    assert status["layers"]["operations"]["revisions"] == 6 and status["refresh_after_sync"] is True
    assert status["builds"][0]["report"]["layers"]["operations"]["extracted"] == 6
    accepted = await client.post(f"{base}/builds", headers=headers, json={"layers": ["manual", "operations"]})
    assert accepted.status_code == 202 and accepted.json()["build"]["state"] == "pending"
    assert (await client.post(f"{base}/builds", headers=headers, json={"layers": ["x"]})).status_code == 422
    await refresh_after_sync(db, authorized.project_id)
    pending = (await db.execute(select(KnowledgeStructuredBuild).where(
        KnowledgeStructuredBuild.project_id == authorized.project_id,
        KnowledgeStructuredBuild.state == "pending"))).scalars().all()
    assert len(pending) == 1 and pending[0].layers == ["manual", "configuration", "operations"]
    other = await seed_workspace(db, name="Never built")
    await refresh_after_sync(db, other)
    assert not (await db.execute(select(KnowledgeStructuredBuild).where(
        KnowledgeStructuredBuild.project_id == other))).scalars().all()


async def test_hit_facts_respect_the_product_bound_and_edge_citations(db):
    from app.models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceHead
    from app.services.knowledge.structured.expansion import structured_hit_facts

    user, authorized = await _full(db)
    change_source = (await db.execute(select(KnowledgeEvidenceSource).where(
        KnowledgeEvidenceSource.source_key == "servicenow.sn.chg"))).scalar_one()
    revision = (await db.get(KnowledgeSourceHead, change_source.id)).current_revision_id
    hits = [(revision, 1)]
    facts = await structured_hit_facts(db, authorized=authorized, hits=hits, products=None, limit=20)
    assert any(item.fact.relation == "MENTIONS" and item.fact.source_entity.startswith("ACME-117")
               for item in facts)
    assert await structured_hit_facts(db, authorized=authorized, hits=hits, products=("spring-boot",), limit=20) == ()
    # The Jira record becomes invisible: its node survives as a stub (mentioned elsewhere), but the
    # edge it states (ACME-117 mentions CHG0000202) rests on it and is no longer served.
    db.add(KnowledgeSourceAcl(project_id=authorized.project_id, source_key="jira.jira-shop.117",
                              restriction="restricted"))
    await db.commit()
    hidden = await structured_hit_facts(db, authorized=authorized, hits=hits, products=None, limit=20)
    assert not any(item.fact.source_entity.startswith("ACME-117") for item in hidden)
    focus = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                        focus_node_id=node_id("Change", "servicenow:CHG0000202"))
    names = {node["id"]: node["display_name"] for node in focus["nodes"]}
    assert not any(names[edge["source"]].startswith("ACME-117") for edge in focus["edges"])


async def test_a_layer_filter_holds_for_query_neighbourhoods_too(db):
    _, authorized = await _full(db)
    graph = await build_workspace_graph(db, runtime=get_evidence_runtime(), authorized=authorized,
                                        query="acme-117", layers=("operations",))
    # A ticket mentioned in a config comment is a stub; the reader sees the Jira record's own statement.
    issue = next(node for node in graph["nodes"] if node["node_type"] == "JiraIssue")
    assert issue["display_name"].startswith("ACME-117 Reduce")
    assert graph["nodes"] and {node["layer"] for node in graph["nodes"]} == {"operations"}
    assert all(edge["layer"] == "operations" for edge in graph["edges"])


async def test_only_authors_request_builds(client, db):
    from app.services.knowledge.access.authorization import authorize_workspace  # noqa: F401
    from tests.knowledge_evidence_seed_support import seed_member

    _, authorized = await _full(db)
    member = await seed_member(db, workspace_id=authorized.project_id, role="member")
    headers = {"Authorization": f"Bearer {create_access_token(member)}"}
    base = f"/api/v1/workspaces/{authorized.project_id}/knowledge/graph/structured"
    assert (await client.post(f"{base}/builds", headers=headers, json={"layers": ["manual"]})).status_code == 403
    assert (await client.get(base, headers=headers)).status_code == 200


async def test_a_comparison_resting_on_a_restricted_file_is_not_served_through_a_visible_hit(db):
    from app.models.project.knowledge_structured import KnowledgeStructuredNode
    from app.services.knowledge.structured.expansion import structured_hit_facts

    _, authorized = await _full(db)
    setting = (await db.execute(select(KnowledgeStructuredNode).where(
        KnowledgeStructuredNode.label == "[QueueConnection] RequestTimeout",
        KnowledgeStructuredNode.properties["component"].as_string() == "conf"))).scalars().first()
    hits = [(setting.revision_id, setting.span_ordinal)]
    visible = await structured_hit_facts(db, authorized=authorized, hits=hits, products=None, query="RequestTimeout",
                                         limit=20)
    assert any(item.fact.relation == "INCONSISTENT_ACROSS" and "worker" in item.fact.fact for item in visible)
    # Without a query naming a key, findings still come before the chunk's structural "defines" edges.
    first = await structured_hit_facts(db, authorized=authorized, hits=hits, products=None, limit=5)
    assert len(first) == 5 and not {item.fact.relation for item in first} & {"DEFINES", "CHANGES_FILE"}
    db.add(KnowledgeSourceAcl(project_id=authorized.project_id,
                              source_key=(await _source_key_of(db, "worker/app.ini")), restriction="restricted"))
    await db.commit()
    hidden = await structured_hit_facts(db, authorized=authorized, hits=hits, products=None, query="RequestTimeout",
                                        limit=20)
    assert not any("worker" in item.fact.fact for item in hidden)
    assert any(item.fact.relation == "INCONSISTENT_ACROSS" for item in hidden)  # conf vs data stays


async def _source_key_of(db, path: str) -> str:
    from app.models.project.knowledge_evidence import KnowledgeEvidenceSource

    return (await db.execute(select(KnowledgeEvidenceSource.source_key).where(
        KnowledgeEvidenceSource.display_title == f"acme-orders-config:{path}"))).scalar_one()
