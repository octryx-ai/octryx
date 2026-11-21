"""Deterministic extractor for a repository's code structure (modules and imports)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..store import upsert_edge, upsert_node
from .common import slugify


async def _ingest_modules(
    db: AsyncSession, *, project_id: str | None, repository: str, modules: list[Any], repo_node: Any
) -> tuple[dict[str, Any], int, int]:
    """``(module node by name and path, nodes, edges)`` for the snapshot's modules."""
    module_by_ref: dict[str, Any] = {}
    nodes = edges = 0
    for module in modules:
        path = str(module.get("path") or "").strip()
        name = str(module.get("name") or path).strip()
        if not (path or name):
            continue
        description = str(module.get("description") or "").strip() or f"Module {name or path} in {repository}"
        properties: dict[str, Any] = {"repository": repository, "path": path}
        language = str(module.get("language") or "").strip()
        if language:
            properties["language"] = language
        node = await upsert_node(
            db,
            project_id=project_id,
            node_type="module",
            node_key=slugify(f"mod-{repository}-{path or name}"),
            display_name=name or path,
            description=description,
            aliases=[value for value in (name, path) if value],
            properties=properties,
            source_refs=[f"repo:{repository}:{path}"],
            # Module basenames repeat across repositories (Dockerfile, main.py):
            # identity must come from the repo-scoped key, never the alias.
            resolve_by_alias=False,
        )
        for ref in (name, path):
            if ref:
                module_by_ref[ref] = node
        nodes += 1
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="part_of",
            source_node_id=node.id,
            target_node_id=repo_node.id,
            description=f"{name or path} part of {repository}",
        )
        edges += 1
    return module_by_ref, nodes, edges


async def _link_imports(
    db: AsyncSession, *, project_id: str | None, modules: list[Any], module_by_ref: dict[str, Any]
) -> int:
    edges = 0
    for module in modules:
        source = module_by_ref.get(str(module.get("name") or module.get("path") or "").strip())
        if source is None:
            continue
        for imported in module.get("imports") or []:
            target = module_by_ref.get(str(imported).strip())
            if target is None:
                continue
            await upsert_edge(
                db,
                project_id=project_id,
                edge_type="imports",
                source_node_id=source.id,
                target_node_id=target.id,
                description=f"{source.display_name} imports {target.display_name}",
            )
            edges += 1
    return edges


async def ingest_code_structure(
    db: AsyncSession, *, project_id: str | None, snapshot: dict[str, Any]
) -> dict[str, int]:
    repository = str(snapshot.get("repository") or "repo")
    repo_node = await upsert_node(
        db,
        project_id=project_id,
        node_type="repository",
        node_key=slugify(f"repo-{repository}"),
        display_name=repository,
        description=f"Repository {repository}",
        source_refs=[f"repo:{repository}"],
    )
    modules = snapshot.get("modules") or []
    module_by_ref, module_nodes, edges = await _ingest_modules(
        db, project_id=project_id, repository=repository, modules=modules, repo_node=repo_node
    )
    edges += await _link_imports(db, project_id=project_id, modules=modules, module_by_ref=module_by_ref)
    return {"nodes": 1 + module_nodes, "edges": edges}
