"""C: the operations graph from ServiceNow, Jira and inventory records, structured fields only."""

from __future__ import annotations

from sqlalchemy import select

from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.models.project.knowledge_structured import KnowledgeStructuredEdge, KnowledgeStructuredNode
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.facts import SpanRef, node_id
from app.services.knowledge.structured.ops_records import extract_inventory, extract_jira, extract_servicenow
from app.services.knowledge.structured.profile import structured_profile
from app.services.knowledge.structured.tickets import jira_pattern
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

INCIDENT = """# INC0000105: Empty quotes from the pricing service after deployment

- Table: incident
- State: In Progress
- Priority: 3 - Moderate
- Impact: 2 - Medium
- Assignment group: Platform Operations
- Business service: Checkout
- Configuration item: shop-pricing
- Opened: 2026-01-04 08:15:00

## Description

The quote endpoint returns empty quotes. Caused by CHG0000202 (RequestTimeout reduced), see ACME-117.
Also compare INC0000105 and UTF-8 handling (SHA-256 is no ticket).

## Comments

- State: Resolved (quoted from a mail, not a field)
"""

CHANGE = """# CHG0000202: Deploy pricing service 2.4.11

- Table: change_request
- State: Closed
- Assignment group: Platform Operations
- Business service: Checkout
- Opened: 2026-01-02 10:00:00
- Closed: 2026-01-03 18:00:00
- Close code: successful

## Description

Rollout of ACME-117 to production.
"""

ISSUE = """# ACME-117: Reduce queue RequestTimeout for checkout requests

- Type: Improvement
- Status: Closed
- Priority: Major
- Resolution: Fixed
- Assignee: Some Person
- Labels: queue, performance
- Components: Checkout - Pricing
- Fix versions: checkout_v2
- Affects versions: checkout_v1
- Created: 2026-01-01T09:00:00.000+0000

## Description

Deployed with CHG0000202.
"""

INVENTORY = """# Kubernetes inventory: namespace acme-orders-test-euc1

Cluster: EKS demo-nonprod-eks (AWS account nonprod, eu-central-1).

## Deployments in acme-orders-test-euc1 (2)

| Deployment | Desired replicas | Ready | Available | Containers (image) | Resources |
|---|---|---|---|---|---|
| orders-data-deployment | 2 | 2 | 2 | ordersdata (123456789012.dkr.ecr.eu-central-1.amazonaws.com/demo-team/acme-orders-baseimage:3.2-3@sha256:bb87) | ordersdata: req - |
| orders-access-deployment | 1 | 1 | 1 | appsrv (ecr.example/shop/acme-orders-app-server:2.1.0-285) | appsrv: req - |
"""

CITE = lambda offset: SpanRef(1)  # noqa: E731 - offsets are checked in the ledger test
JIRA = jira_pattern(("ACME",))


def _edges(extraction):
    return {(kind, source.node_key, target.node_key) for kind, source, target in extraction.edges}


def test_a_servicenow_incident_yields_typed_fields_group_service_ci_and_its_cause():
    extraction = extract_servicenow(INCIDENT, CITE, structured_profile(), JIRA)
    record = next(node for ref, node in extraction.nodes.items() if ref.node_type == "Incident")
    # Facts are read from the header only: a "- State:" line in the comments is no field.
    assert record.properties["state"] == "In Progress" and record.properties["opened_at"] == "2026-01-04T08:15:00"
    assert record.properties["stub"] is False and record.label.startswith("INC0000105 Empty quotes")
    edges = _edges(extraction)
    assert ("assigned_to_group", "servicenow:INC0000105", "group:Platform Operations") in edges
    assert ("affects_service", "servicenow:INC0000105", "service:Checkout") in edges
    assert ("affects_ci", "servicenow:INC0000105", "ci:shop-pricing") in edges
    assert ("caused_by", "servicenow:INC0000105", "servicenow:CHG0000202") in edges
    assert ("mentions", "servicenow:INC0000105", "jira:ACME-117") in edges
    # Its own number, UTF-8 and SHA-256 are no ticket mentions.
    assert {target for kind, _, target in edges if kind == "mentions"} == {"jira:ACME-117"}


def test_a_change_mentioned_without_a_cause_pattern_is_a_mention_not_a_cause():
    extraction = extract_servicenow(CHANGE, CITE, structured_profile(), JIRA)
    edges = _edges(extraction)
    assert ("mentions", "servicenow:CHG0000202", "jira:ACME-117") in edges
    assert not any(kind == "caused_by" for kind, _, _ in edges)
    stub = extraction.nodes[next(ref for ref in extraction.nodes if ref.node_key == "jira:ACME-117")]
    assert stub.properties["stub"] is True


def test_a_jira_issue_yields_component_versions_and_mentions_but_no_person_nodes():
    extraction = extract_jira(ISSUE, CITE, structured_profile(), JIRA)
    issue = next(node for ref, node in extraction.nodes.items() if ref.node_type == "JiraIssue")
    assert issue.properties["labels"] == ["queue", "performance"] and issue.properties["type"] == "Improvement"
    assert "Some Person" not in repr(extraction.nodes)
    edges = _edges(extraction)
    assert ("in_component", "jira:ACME-117", "jira-component:ACME/Checkout - Pricing") in edges
    assert ("released_in", "jira:ACME-117", "jira-version:ACME/checkout_v2") in edges
    assert ("affects_version", "jira:ACME-117", "jira-version:ACME/checkout_v1") in edges
    assert ("mentions", "jira:ACME-117", "servicenow:CHG0000202") in edges


def test_the_inventory_yields_deployments_in_namespaces_in_clusters_with_image_versions():
    edges = _edges(extract_inventory(INVENTORY, CITE, structured_profile()))
    cluster, namespace = "k8s-cluster:demo-nonprod-eks", "k8s-namespace:demo-nonprod-eks/acme-orders-test-euc1"
    deployment = "k8s-deployment:demo-nonprod-eks/acme-orders-test-euc1/orders-data-deployment"
    assert ("runs_in", namespace, cluster) in edges and ("runs_in", deployment, namespace) in edges
    assert ("uses_image", deployment, "image:acme-orders-baseimage:3.2-3") in edges
    appsrv = "k8s-deployment:demo-nonprod-eks/acme-orders-test-euc1/orders-access-deployment"
    assert ("uses_image", appsrv, "image:acme-orders-app-server:2.1.0-285") in edges


def test_records_of_an_unknown_shape_are_skipped_with_a_warning_not_guessed():
    profile = structured_profile()
    assert extract_servicenow("# Something else\n- Table: sys_user\n", CITE, profile, JIRA).warnings == {
        "record_shape_unknown": 1}
    assert not extract_jira("no heading", CITE, profile, JIRA).nodes
    request = extract_servicenow("# RITM0001234: Access\n\n- Table: sc_req_item\n", CITE, profile, JIRA)
    assert not request.nodes and request.warnings["record_shape_unknown"] == 1
    assert extract_inventory("# Kubernetes inventory: namespace x\n", CITE, structured_profile()).warnings["inventory_shape_unknown"] == 1


async def test_the_operations_layer_builds_cited_records_through_the_ledger(db):
    project_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=project_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=project_id)
    runtime, _, evidence_index = build_runtime()
    db.add(KnowledgeSourceConnector(project_id=project_id, connector_key="jira-shop", kind="jira",
                                    scope={"project_keys": ["ACME"]}, products=[], cursor={}))
    await db.commit()
    for key, title, text in (
        ("servicenow.sn-shop.a1", "INC0000105: Empty quotes", INCIDENT),
        ("servicenow.sn-shop.a2", "CHG0000202: Deploy", CHANGE),
        ("jira.jira-shop.117", "ACME-117: Reduce", ISSUE),
        ("kubernetes.k8s-shop.acme-orders-test-euc1", "Kubernetes inventory: acme-orders-test-euc1", INVENTORY),
        ("notes", "Team notes mentioning CHG0000202", "# Notes\n\nCHG0000202 was fine.\n"),
    ):
        await ingest_text_source(db, runtime=runtime, authorized=authorized, source_key=key, display_title=title,
                                 declared_media_type="text/markdown", data=text.encode(), created_by=user_id)
    while await EvidenceProjector(runtime).project_once(db, worker_id="test") is not None:
        pass
    build = await request_build(db, project_id=project_id, layers=["operations"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    assert await run_build_slice(db, runtime=runtime, build_id=build.id, worker_id="w") == "completed"
    await db.refresh(build)
    layer = build.report["layers"]["operations"]
    assert layer["selected"] == 4 and layer["extracted"] == 4 and layer["warnings"] == {}  # notes are not selected
    incident = node_id("Incident", "servicenow:INC0000105")
    cause = (await db.execute(select(KnowledgeStructuredEdge).where(
        KnowledgeStructuredEdge.source_id == incident, KnowledgeStructuredEdge.edge_type == "caused_by"))).scalar_one()
    assert cause.target_id == node_id("Change", "servicenow:CHG0000202") and cause.layer == "operations"
    statements = (await db.execute(select(KnowledgeStructuredNode).where(
        KnowledgeStructuredNode.node_id == node_id("Change", "servicenow:CHG0000202")))).scalars().all()
    # Its own record plus the stubs from the incident and the Jira issue that mention it.
    assert sorted(row.properties["stub"] for row in statements) == [False, True, True]
    assert all(row.span_ordinal >= 1 for row in statements)


async def test_a_reader_sees_the_records_own_statement_not_a_stub_of_it(db):
    from app.services.knowledge.structured.read import visible_nodes
    from tests.structured_graph_support import seed_parsed_revision, span

    project_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=project_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=project_id)
    revisions = sorted([
        (await seed_parsed_revision(db, project_id, source_key=f"s{n}", title=f"S{n}", spans=[span(1, "x")]))[1]
        for n in range(2)
    ])
    change = node_id("Change", "servicenow:CHG0000202")
    for revision, stub, label in ((revisions[0], True, "CHG0000202"), (revisions[1], False, "CHG0000202 Deploy")):
        db.add(KnowledgeStructuredNode(project_id=project_id, revision_id=revision, profile="structured-v4",
                                       layer="operations", node_type="Change", node_key="servicenow:CHG0000202",
                                       node_id=change, label=label, properties={"stub": stub}, span_ordinal=1))
    await db.commit()
    view = (await visible_nodes(db, authorized, {change}))[change]
    assert view.label == "CHG0000202 Deploy" and view.revisions == set(revisions)
