"""Terraform stacks: one ``infrastructure_stack`` node per stack directory plus its resources."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import resolve_node_by_alias, upsert_edge, upsert_node
from ..common import slugify
from ..structured import ingest_terraform

_MAX_TF_ADDRESSES_NAMED = 20


def _stack_description(
    stack: dict[str, Any], path: str, repository: str, resources: list[dict[str, Any]], modules: list[dict[str, Any]]
) -> str:
    providers = [str(p) for p in (stack.get("providers") or []) if str(p).strip()]
    type_counts: dict[str, int] = {}
    for resource in resources:
        rtype = str(resource.get("type") or "resource")
        type_counts[rtype] = type_counts.get(rtype, 0) + 1
    type_summary = ", ".join(
        f"{count}x {rtype}" for rtype, count in sorted(type_counts.items(), key=lambda kv: -kv[1])[:12]
    )
    named = ", ".join(str(r["address"]) for r in resources[:_MAX_TF_ADDRESSES_NAMED])
    module_summary = ", ".join(
        str(m["name"]) + (f" ({m['source']})" if m.get("source") else "") for m in modules[:10]
    )
    parts = [f"Terraform stack {path} in {repository}"]
    if providers:
        parts.append(f"Providers: {', '.join(providers[:8])}")
    if type_summary:
        parts.append(f"Provisions {len(resources)} resources: {type_summary}")
    if named:
        parts.append(f"Includes: {named}")
    if module_summary:
        parts.append(f"Uses modules: {module_summary}")
    return ". ".join(parts) + "."


async def _link_resources(
    db: AsyncSession, *, project_id: str | None, resources: list[dict[str, Any]], stack_node: Any, path: str,
    source_ref: str,
) -> tuple[int, int]:
    # Resource nodes keyed by tf address; name == address avoids fuzzy
    # alias merges on template names like "this"/"main".
    tf_counts = await ingest_terraform(
        db,
        project_id=project_id,
        snapshot={
            "resources": [
                {"address": r["address"], "name": r["address"], "type": r.get("type")} for r in resources
            ]
        },
    )
    nodes = int(tf_counts.get("nodes") or 0)
    edges = 0
    for resource in resources:
        resource_node = await resolve_node_by_alias(
            db, project_id=project_id, alias=str(resource["address"])
        )
        if resource_node is None:
            continue
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="part_of",
            source_node_id=resource_node.id,
            target_node_id=stack_node.id,
            description=f"{resource['address']} defined in stack {path}"
            + (f" ({resource.get('file')})" if resource.get("file") else ""),
            source_refs=[source_ref],
        )
        edges += 1
    return nodes, edges


async def _ingest_terraform_stacks(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any], repo_node: Any, repository: str,
    source_ref: str,
) -> tuple[int, int]:
    nodes = edges = 0
    for stack in record.get("terraform_stacks") or []:
        if not isinstance(stack, dict):
            continue
        path = str(stack.get("path") or "").strip()
        resources = [r for r in (stack.get("resources") or []) if isinstance(r, dict) and r.get("address")]
        modules = [m for m in (stack.get("modules") or []) if isinstance(m, dict) and m.get("name")]
        if not path or not (resources or modules):
            continue
        stack_node = await upsert_node(
            db,
            project_id=project_id,
            node_type="infrastructure_stack",
            node_key=slugify(f"tfstack-{repository}-{path}"),
            display_name=path.rsplit("/", 1)[-1],
            description=_stack_description(stack, path, repository, resources, modules),
            aliases=[path, path.rsplit("/", 1)[-1]],
            properties={"repository": repository, "path": path, "iac": "terraform"},
            source_refs=[source_ref],
            resolve_by_alias=False,
        )
        nodes += 1
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="part_of",
            source_node_id=stack_node.id,
            target_node_id=repo_node.id,
            description=f"Terraform stack {path} part of {repository}",
            source_refs=[source_ref],
        )
        edges += 1
        added_nodes, added_edges = await _link_resources(
            db, project_id=project_id, resources=resources, stack_node=stack_node, path=path, source_ref=source_ref
        )
        nodes += added_nodes
        edges += added_edges
    return nodes, edges
