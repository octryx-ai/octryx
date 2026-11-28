"""Deterministic extractors for structured sources."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..store import upsert_edge, upsert_node
from .common import slugify

_STRUCTURAL_RELATIONS = {"depends_on", "part_of", "contains", "references"}


async def ingest_aws_topology(db: AsyncSession, *, project_id: str | None, snapshot: dict[str, Any]) -> dict[str, int]:
    account = str(snapshot.get("account_id") or "aws")
    region = str(snapshot.get("region") or "")
    node_by_ext: dict[str, Any] = {}
    nodes = edges = 0
    for resource in snapshot.get("resources") or []:
        ext_id = str(resource.get("id") or resource.get("name") or "").strip()
        if not ext_id:
            continue
        name = str(resource.get("name") or ext_id)
        rtype = str(resource.get("type") or "resource")
        service = str(resource.get("service") or "")
        node = await upsert_node(
            db,
            project_id=project_id,
            node_type="resource",
            node_key=slugify(f"aws-{ext_id}"),
            display_name=name,
            description=f"AWS {rtype} {name} ({service}) in {region}".strip(),
            aliases=[ext_id, name],
            properties={"cloud": "aws", "aws_type": rtype, "service": service, "region": region, "account_id": account},
            source_refs=[f"aws:{account}:{ext_id}"],
        )
        node_by_ext[ext_id] = node
        nodes += 1
    for dependency in snapshot.get("dependencies") or []:
        source = node_by_ext.get(str(dependency.get("source") or "").strip())
        target = node_by_ext.get(str(dependency.get("target") or "").strip())
        if source is None or target is None:
            continue
        relation = str(dependency.get("relation") or "depends_on").strip().lower()
        relation = relation if relation in _STRUCTURAL_RELATIONS else "depends_on"
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type=relation,
            source_node_id=source.id,
            target_node_id=target.id,
            description=f"{source.display_name} {relation} {target.display_name}",
        )
        edges += 1
    return {"nodes": nodes, "edges": edges}


async def ingest_terraform(db: AsyncSession, *, project_id: str | None, snapshot: dict[str, Any]) -> dict[str, int]:
    node_by_addr: dict[str, Any] = {}
    nodes = edges = 0
    resources = snapshot.get("resources") or []
    for resource in resources:
        address = str(resource.get("address") or "").strip()
        if not address:
            continue
        name = str(resource.get("name") or address)
        rtype = str(resource.get("type") or "resource")
        node = await upsert_node(
            db,
            project_id=project_id,
            node_type="resource",
            node_key=slugify(f"tf-{address}"),
            display_name=address,
            description=f"Terraform {rtype} {name} (provider {resource.get('provider', '')})".strip(),
            aliases=[address, name],
            properties={"iac": "terraform", "tf_type": rtype},
            source_refs=[f"terraform:{address}"],
        )
        node_by_addr[address] = node
        nodes += 1
    for resource in resources:
        source = node_by_addr.get(str(resource.get("address") or "").strip())
        if source is None:
            continue
        for dependency in resource.get("depends_on") or []:
            target = node_by_addr.get(str(dependency).strip())
            if target is None:
                continue
            await upsert_edge(
                db,
                project_id=project_id,
                edge_type="depends_on",
                source_node_id=source.id,
                target_node_id=target.id,
                description=f"{source.display_name} depends on {target.display_name}",
            )
            edges += 1
    return {"nodes": nodes, "edges": edges}


async def _ingest_tables(
    db: AsyncSession, *, project_id: str | None, database: str, schema: str, tables: list[Any], db_node: Any
) -> tuple[dict[str, Any], int, int]:
    table_by_name: dict[str, Any] = {}
    nodes = edges = 0
    for table in tables:
        name = str(table.get("name") or "").strip()
        if not name:
            continue
        columns = [
            {"name": str(column.get("name")), "type": str(column.get("type") or "")}
            for column in (table.get("columns") or [])
            if column.get("name")
        ]
        column_summary = ", ".join(f"{column['name']} {column['type']}".strip() for column in columns[:30])
        node = await upsert_node(
            db,
            project_id=project_id,
            node_type="table",
            node_key=slugify(f"tbl-{database}-{name}"),
            display_name=name,
            description=f"Table {name} with columns: {column_summary}".strip(),
            aliases=[name],
            properties={"database": database, "schema": schema, "columns": columns},
            source_refs=[f"db:{database}:{name}"],
        )
        table_by_name[name] = node
        nodes += 1
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="contains",
            source_node_id=db_node.id,
            target_node_id=node.id,
            description=f"{database} contains table {name}",
        )
        edges += 1
    return table_by_name, nodes, edges


async def _link_foreign_keys(
    db: AsyncSession, *, project_id: str | None, tables: list[Any], table_by_name: dict[str, Any]
) -> int:
    edges = 0
    for table in tables:
        source = table_by_name.get(str(table.get("name") or "").strip())
        if source is None:
            continue
        for foreign_key in table.get("foreign_keys") or []:
            target = table_by_name.get(str(foreign_key.get("references_table") or "").strip())
            if target is None:
                continue
            await upsert_edge(
                db,
                project_id=project_id,
                edge_type="references",
                source_node_id=source.id,
                target_node_id=target.id,
                description=(
                    f"{source.display_name}.{foreign_key.get('column')} references "
                    f"{target.display_name}.{foreign_key.get('references_column')}"
                ),
            )
            edges += 1
    return edges


async def ingest_database_schema(
    db: AsyncSession, *, project_id: str | None, snapshot: dict[str, Any]
) -> dict[str, int]:
    """Ingest a database SCHEMA (tables/columns/foreign keys) — never row data."""
    database = str(snapshot.get("database") or "db")
    schema = str(snapshot.get("schema") or "")
    db_node = await upsert_node(
        db,
        project_id=project_id,
        node_type="database",
        node_key=slugify(f"db-{database}-{schema}"),
        display_name=f"{database}.{schema}".strip("."),
        description=f"Database {database} schema {schema}".strip(),
        source_refs=[f"db:{database}"],
    )
    tables = snapshot.get("tables") or []
    table_by_name, table_nodes, edges = await _ingest_tables(
        db, project_id=project_id, database=database, schema=schema, tables=tables, db_node=db_node
    )
    edges += await _link_foreign_keys(db, project_id=project_id, tables=tables, table_by_name=table_by_name)
    return {"nodes": 1 + table_nodes, "edges": edges}


async def ingest_topology_snapshot(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any]
) -> dict[str, int] | None:
    """Adapt a compact connector topology bronze value to the resource-graph shape ``ingest_aws_topology`` expects."""
    nodes = [n for n in (record.get("selected_nodes") or []) if isinstance(n, dict)]
    if not nodes:
        return None
    edges = [e for e in (record.get("selected_edges") or []) if isinstance(e, dict)]
    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    snapshot = {
        "account_id": scope.get("account_id") or record.get("connector_name") or "unknown",
        "region": scope.get("region") or "",
        "resources": [
            {
                "id": n.get("id") or n.get("ref"),
                "name": n.get("label") or n.get("id") or n.get("ref"),
                "type": n.get("type") or n.get("service") or "resource",
                "service": n.get("service"),
            }
            for n in nodes
            if (n.get("id") or n.get("ref"))
        ],
        "dependencies": [
            {
                "source": e.get("source") or e.get("source_ref"),
                "target": e.get("target") or e.get("target_ref"),
                "relation": e.get("type") or e.get("label") or "depends_on",
            }
            for e in edges
            if (e.get("source") or e.get("source_ref")) and (e.get("target") or e.get("target_ref"))
        ],
    }
    return await ingest_aws_topology(db, project_id=project_id, snapshot=snapshot)
