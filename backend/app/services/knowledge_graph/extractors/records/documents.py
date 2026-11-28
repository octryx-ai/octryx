"""Documentation page records (e.g. Confluence) as document nodes with contributors."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import add_claim, upsert_edge, upsert_node
from ..common import slugify
from .people import _CONTRIBUTION_EDGE_BY_ROLE, ingest_person_from_source


async def _link_contributors(
    db: AsyncSession, *, project_id: str | None, page: dict[str, Any], document: Any, title: str, source_ref: str
) -> str:
    linked: set[tuple[str, str]] = set()
    updated_by_display = ""
    for person in page.get("source_people") or []:
        if not isinstance(person, dict):
            continue
        role = str(person.get("role") or "").strip().lower()
        edge_type = _CONTRIBUTION_EDGE_BY_ROLE.get(role)
        if edge_type is None:
            continue
        node = await ingest_person_from_source(db, project_id=project_id, person=person, source_ref=source_ref)
        if node is None or (edge_type, node.id) in linked:
            continue
        linked.add((edge_type, node.id))
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type=edge_type,
            source_node_id=node.id,
            target_node_id=document.id,
            description=f"{node.display_name} {role} of {title}",
            source_refs=[source_ref],
        )
        if role == "updated_by":
            updated_by_display = node.display_name
    return updated_by_display


async def ingest_document_record(
    db: AsyncSession,
    *,
    project_id: str | None,
    page: dict[str, Any],
) -> Any | None:
    """Map a documentation page record into the graph: a document node, its authors and contributors, and a version
    claim."""
    title = str(page.get("title") or "").strip()
    page_id = str(page.get("page_id") or "").strip()
    if not (title or page_id):
        return None
    source_ref = f"confluence:{page_id}" if page_id else f"doc:{slugify(title)}"
    space = str(page.get("space_key") or "").strip()
    document = await upsert_node(
        db,
        project_id=project_id,
        node_type="document",
        node_key=slugify(f"page-{page_id or title}"),
        display_name=title or page_id,
        description=str(page.get("summary") or "").strip(),
        aliases=[value for value in (title, page_id, page.get("url")) if value],
        properties={
            "space_key": space,
            "page_id": page_id,
            "url": page.get("url"),
            "page_version": page.get("page_version"),
        },
        source_refs=[source_ref],
    )

    updated_by_display = await _link_contributors(
        db, project_id=project_id, page=page, document=document, title=title, source_ref=source_ref
    )

    page_version = page.get("page_version")
    if page_version:
        actor = updated_by_display or "unknown"
        updated_when = str(page.get("updated_when") or "").strip()
        await add_claim(
            db,
            project_id=project_id,
            subject_node_id=document.id,
            statement=f"Version {page_version} updated by {actor}"
            + (f" on {updated_when}" if updated_when else ""),
            claim_type="version",
            valid_from_label=f"v{page_version}",
            source_refs=[source_ref],
        )
    return document
