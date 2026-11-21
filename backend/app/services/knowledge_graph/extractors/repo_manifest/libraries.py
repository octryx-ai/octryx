"""Library dependencies: one node per library, shared across repositories."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import upsert_edge, upsert_node
from ..common import slugify

_MAX_LIBRARIES = 200


async def _ingest_libraries(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any], repo_node: Any, repository: str,
    source_ref: str,
) -> tuple[int, int]:
    """``(nodes, edges)`` written for the record's dependencies."""
    nodes = edges = 0
    # Libraries: one node per (ecosystem, name) shared across all repositories.
    seen_libraries: set[str] = set()
    for dep in (record.get("dependencies") or [])[: _MAX_LIBRARIES * 2]:
        if not isinstance(dep, dict):
            continue
        name = str(dep.get("name") or "").strip()
        ecosystem = str(dep.get("ecosystem") or "unknown").strip()
        if not name or name in seen_libraries or len(seen_libraries) >= _MAX_LIBRARIES:
            continue
        seen_libraries.add(name)
        version = str(dep.get("version") or "").strip()
        manifest = str(dep.get("manifest") or "").strip()
        library = await upsert_node(
            db,
            project_id=project_id,
            node_type="library",
            node_key=slugify(f"lib-{ecosystem}-{name}"),
            display_name=name,
            description=f"Library {name} ({ecosystem})",
            aliases=[value for value in {name, str(dep.get("artifact") or "").strip()} if value],
            properties={"ecosystem": ecosystem},
            source_refs=[source_ref],
            resolve_by_alias=False,
        )
        nodes += 1
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="depends_on",
            source_node_id=repo_node.id,
            target_node_id=library.id,
            description=f"{repository} depends on {name}"
            + (f" {version}" if version else "")
            + (f" ({manifest})" if manifest else ""),
            source_refs=[source_ref],
        )
        edges += 1
    return nodes, edges
