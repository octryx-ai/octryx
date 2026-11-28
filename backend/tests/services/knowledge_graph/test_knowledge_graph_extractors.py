"""Deterministic structured extractors: AWS, Terraform, DB schema, code, and the
cross-source linking (a Terraform resource and its AWS counterpart become one node)."""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge_graph import (
    get_neighbors,
    ingest_aws_topology,
    ingest_code_structure,
    ingest_database_schema,
    ingest_terraform,
    resolve_node_by_alias,
    upsert_node,
)
from app.services.knowledge_graph.store import _node_aliases


@pytest.mark.asyncio
async def test_aws_topology_maps_resources_and_dependencies(db):
    token = uuid.uuid4().hex[:8]
    snapshot = {
        "account_id": f"acct-{token}",
        "region": "eu-central-1",
        "resources": [
            {"id": f"i-{token}", "name": f"orders-api-{token}", "type": "ec2", "service": "compute"},
            {"id": f"db-{token}", "name": f"orders-db-{token}", "type": "rds", "service": "database"},
        ],
        "dependencies": [{"source": f"i-{token}", "target": f"db-{token}", "relation": "depends_on"}],
    }
    result = await ingest_aws_topology(db, project_id=None, snapshot=snapshot)
    assert result["nodes"] == 2 and result["edges"] == 1

    api = await resolve_node_by_alias(db, project_id=None, alias=f"orders-api-{token}")
    assert api is not None
    neighbors = await get_neighbors(db, node_id=api.id)
    assert any(n["edge_type"] == "depends_on" for n in neighbors)


@pytest.mark.asyncio
async def test_terraform_links_to_aws_resource_via_alias(db):
    token = uuid.uuid4().hex[:8]
    name = f"orders-api-{token}"
    await ingest_aws_topology(
        db,
        project_id=None,
        snapshot={"account_id": f"a-{token}", "resources": [{"id": f"i-{token}", "name": name, "type": "ec2"}]},
    )
    await ingest_terraform(
        db,
        project_id=None,
        snapshot={"resources": [{"address": f"aws_instance.{name}", "name": name, "type": "aws_instance"}]},
    )
    # The AWS resource id, the display name, and the Terraform address all resolve
    # to the SAME node — one entity across two sources.
    by_aws = await resolve_node_by_alias(db, project_id=None, alias=f"i-{token}")
    by_name = await resolve_node_by_alias(db, project_id=None, alias=name)
    by_tf = await resolve_node_by_alias(db, project_id=None, alias=f"aws_instance.{name}")
    assert by_aws is not None
    assert by_aws.id == by_name.id == by_tf.id


@pytest.mark.asyncio
async def test_database_schema_ingests_structure_not_rows(db):
    token = uuid.uuid4().hex[:8]
    snapshot = {
        "database": f"appdb-{token}",
        "schema": "public",
        "tables": [
            {
                "name": f"orders-{token}",
                "columns": [{"name": "id", "type": "uuid"}, {"name": "customer_id", "type": "uuid"}],
                "foreign_keys": [{"column": "customer_id", "references_table": f"customers-{token}", "references_column": "id"}],
            },
            {"name": f"customers-{token}", "columns": [{"name": "id", "type": "uuid"}]},
        ],
    }
    result = await ingest_database_schema(db, project_id=None, snapshot=snapshot)
    assert result["nodes"] == 3  # database + 2 tables
    # contains (db->table) x2 + references (orders->customers) x1
    assert result["edges"] == 3

    orders = await resolve_node_by_alias(db, project_id=None, alias=f"orders-{token}")
    assert orders is not None
    # Columns are captured as schema structure in properties — never row data.
    assert isinstance(orders.properties.get("columns"), list)
    assert {c["name"] for c in orders.properties["columns"]} == {"id", "customer_id"}
    neighbors = await get_neighbors(db, node_id=orders.id)
    assert any(n["edge_type"] == "references" for n in neighbors)


@pytest.mark.asyncio
async def test_code_structure_maps_modules_and_imports(db):
    token = uuid.uuid4().hex[:8]
    snapshot = {
        "repository": f"orders-repo-{token}",
        "modules": [
            {"path": "app/api.py", "name": f"api-{token}", "imports": [f"db-{token}"]},
            {"path": "app/db.py", "name": f"db-{token}", "imports": []},
        ],
    }
    result = await ingest_code_structure(db, project_id=None, snapshot=snapshot)
    assert result["nodes"] == 3  # repo + 2 modules
    api = await resolve_node_by_alias(db, project_id=None, alias=f"api-{token}")
    assert api is not None
    neighbors = await get_neighbors(db, node_id=api.id)
    assert any(n["edge_type"] == "imports" for n in neighbors)
    assert any(n["edge_type"] == "part_of" for n in neighbors)


@pytest.mark.asyncio
async def test_alias_helper_records_multiple_identifiers(db):
    token = uuid.uuid4().hex[:8]
    node = await upsert_node(
        db, project_id=None, node_type="service", node_key=f"svc-{token}",
        display_name=f"Orders Service {token}", description="orders", aliases=[f"orders-{token}"],
    )
    aliases = {a.normalized_alias for a in await _node_aliases(db, node.id)}
    assert f"orders-{token}" in aliases


@pytest.mark.asyncio
async def test_topology_snapshot_adapter_maps_compact_nodes_and_edges(db):
    from app.services.knowledge_graph.extractors import ingest_topology_snapshot

    token = uuid.uuid4().hex[:8]
    record = {
        "connector_name": "aws",
        "scope": {"account_id": f"acct-{token}", "region": "eu-central-1"},
        "selected_nodes": [
            {"id": f"i-{token}", "label": f"orders-api-{token}", "type": "ec2", "service": "compute"},
            {"id": f"db-{token}", "label": f"orders-db-{token}", "type": "rds", "service": "database"},
        ],
        "selected_edges": [{"source": f"i-{token}", "target": f"db-{token}", "type": "connects_to"}],
    }
    counts = await ingest_topology_snapshot(db, project_id=None, record=record)
    assert counts is not None and counts["nodes"] == 2 and counts["edges"] == 1

    api = await resolve_node_by_alias(db, project_id=None, alias=f"orders-api-{token}")
    assert api is not None
    neighbors = await get_neighbors(db, node_id=api.id)
    # Non-whitelisted relations normalize to depends_on (ontology-bounded edges).
    assert any(n["edge_type"] == "depends_on" for n in neighbors)
