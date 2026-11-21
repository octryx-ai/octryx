"""Reading the structured graph for one reader: visibility, nodes and presented citations.

Nothing is served on trust. A row is visible to a reader only when every revision it cites is
the current, projected revision of a source the reader may see (``visible_source`` with the
reader's principal keys) inside the authorized Workspace; this is the same rule
``resolve_citations`` applies span by span, evaluated once per revision so a report over thousands
of edges stays one query. The citations actually shown are then resolved span by span with
``resolve_citations`` and presented like every Knowledge citation (``cite_as`` link, page or line).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from ....models.project.knowledge_structured import KnowledgeStructuredNode
from ..access.authorization import AuthorizedWorkspace
from ..access.source_acl import visible_source
from ..ingestion.spans import derive_evidence_key
from ..ledger.citations import ResolvedCitation, resolve_citations
from ..retrieval.locator import citation_link
from ..sources.source_url import line_link

Cite = tuple[str, int, int | None]
CHUNK = 500


def cites_of(raw: object) -> list[Cite]:
    found = []
    for item in raw or ():
        if isinstance(item, (list, tuple)) and len(item) == 3 and isinstance(item[0], str) and type(item[1]) is int:
            found.append((item[0], item[1], item[2] if type(item[2]) is int else None))
    return found


async def visible_revisions(db: AsyncSession, authorized: AuthorizedWorkspace, revision_ids: set[str]) -> set[str]:
    """The cited revisions this reader may see: current, projected, and admitted by the source ACL."""
    project_id = authorized.project_id
    wanted, visible = sorted(revision_ids), set()
    for start in range(0, len(wanted), CHUNK):
        rows = await db.execute(
            select(KnowledgeSourceRevision.id)
            .join(KnowledgeSourceHead, KnowledgeSourceHead.current_revision_id == KnowledgeSourceRevision.id)
            .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
            .where(
                KnowledgeSourceRevision.id.in_(wanted[start : start + CHUNK]),
                KnowledgeSourceRevision.project_id == project_id,
                KnowledgeEvidenceSource.project_id == project_id,
                KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
                visible_source(project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
            )
        )
        visible.update(str(row[0]) for row in rows.all())
    return visible


@dataclass(slots=True)
class NodeView:
    node_id: str
    node_type: str
    layer: str
    label: str
    properties: dict[str, Any]
    cite: Cite | None
    revisions: set[str] = field(default_factory=set)


async def visible_nodes(
    db: AsyncSession, authorized: AuthorizedWorkspace, node_ids: set[str], *, visible: set[str] | None = None
) -> dict[str, NodeView]:
    """Each node as its first visible statement says it (by revision, then span)."""
    rows: list[Any] = []
    wanted = sorted(node_ids)
    for start in range(0, len(wanted), CHUNK):
        result = await db.execute(
            select(KnowledgeStructuredNode)
            .where(
                KnowledgeStructuredNode.project_id == authorized.project_id,
                KnowledgeStructuredNode.node_id.in_(wanted[start : start + CHUNK]),
            )
            .order_by(KnowledgeStructuredNode.node_id, KnowledgeStructuredNode.revision_id)
        )
        rows.extend(result.scalars().all())
    if visible is None:
        visible = await visible_revisions(db, authorized, {row.revision_id for row in rows})
    views: dict[str, NodeView] = {}
    for row in rows:
        if row.revision_id not in visible:
            continue
        view = views.get(row.node_id)
        # A record's own statement wins over a stub made from a mention of it elsewhere.
        if view is None or (view.properties.get("stub") and not (row.properties or {}).get("stub")):
            cite = (row.revision_id, row.span_ordinal, row.line) if row.span_ordinal else None
            revisions = view.revisions if view is not None else set()
            view = views[row.node_id] = NodeView(row.node_id, row.node_type, row.layer, row.label,
                                                 dict(row.properties or {}), cite, revisions)
        view.revisions.add(row.revision_id)
    return views


def present(resolved: ResolvedCitation, line: int | None = None) -> dict[str, Any]:
    """A citation as the explorer and the tools show it; a file line opens exactly that line."""
    if line is not None:
        base = (resolved.source_url or "").split("#", 1)[0] or None
        resolved = dataclasses.replace(resolved, source_url=line_link(base, line, line), line_start=line, line_end=line)
    return {
        "citation": resolved.citation,
        "cite_as": citation_link(resolved),
        "evidence_key": resolved.evidence_key,
        "source_title": resolved.source_title,
        "source_url": resolved.source_url,
        "section": " > ".join(resolved.section_path) or None,
        "page": resolved.page_start,
        "line": line,
        "source_id": resolved.source_id,
        "revision_id": resolved.revision_id,
    }


async def presented_citations(
    db: AsyncSession, authorized: AuthorizedWorkspace, cites: list[Cite]
) -> dict[Cite, dict[str, Any]]:
    """Resolve and present citations for this reader; a citation that does not resolve is absent."""
    keys = {cite: derive_evidence_key(cite[0], cite[1]) for cite in cites}
    resolved = await resolve_citations(
        db, authorized.project_id, tuple(sorted(set(keys.values()))), principal_keys=authorized.principal_keys
    )
    return {cite: present(resolved[key], cite[2]) for cite, key in keys.items() if key in resolved}


__all__ = [
    "Cite",
    "NodeView",
    "cites_of",
    "present",
    "presented_citations",
    "visible_nodes",
    "visible_revisions",
]
