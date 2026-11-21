"""The "Handbook vs. reality" report for one Workspace and one reader.

Counts and bounded lists from the configuration layer's linkage edges, each item cited (manual
page and section, file and line) and served only when every revision it rests on is visible to
the reader. Every finding is stated once per base file; its ``variants`` (``app.ini-test``) are
listed with their values:

- ``undocumented_in_known_section``: settings no documented parameter covers although the manual
  documents their section, with the same-name parameters of other scopes;
- ``unknown_section``: sections (a sectionless file counts as one) the manual documents nothing
  of, with their keys and the same-name hints of those keys (``[QueueConnection] RequestTimeout`` →
  ``[Cache?] RequestTimeout``, p. 125); ``unknown_section_settings`` counts their keys;
- ``deviations``: configured values (placeholders resolved) that differ from the documented default;
- ``unresolved_placeholders``: configured values with a placeholder (``${Name}``) no source
  defines; never compared with the default;
- ``inconsistencies``: one key with different values across components (``conf`` 500 vs ``data``
  60000), grouped by key;
- ``documented_unused``: parameters of a scope in use that no file sets.

Filters (``parameter``, ``file``, ``section``) narrow every list the same way; the tool
``config_vs_manual`` is this report with a filter. States: ``ok``, ``not_built`` (no configuration
layer yet), ``no_manual`` (no documented parameters to compare with).

The linkage edges are read per type with a cap (:data:`MAX_EDGES_PER_TYPE`; same-name hints, at most
``MAX_NAME_MATCHES`` per finding, get that many times the cap) before anything is loaded; a capped
type marks the report ``edges_capped`` (and ``truncated``), so a huge Workspace costs a bounded
read, never an unbounded one.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_structured import (
    KnowledgeStructuredBuild,
    KnowledgeStructuredEdge,
    KnowledgeStructuredExtraction,
    KnowledgeStructuredNode,
)
from ..access.authorization import AuthorizedWorkspace
from .config_linkage_rules import MAX_NAME_MATCHES
from .config_report_findings import select_findings
from .config_report_items import fill_lists, wanted_citations
from .profile_types import LAYER_CONFIGURATION, LAYER_MANUAL
from .read import cites_of, presented_citations, visible_nodes, visible_revisions
from .workspace_profile import workspace_profile_id

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_FILTER_CHARS = 200
MAX_EDGES_PER_TYPE = 5000
_TYPES = ("configures", "undocumented", "unknown_section", "name_matches", "deviates_from_default",
          "unresolved_placeholder", "inconsistent_across", "documented_unused")
_LISTS = ("undocumented_in_known_section", "unknown_section", "deviations", "unresolved_placeholders",
          "inconsistencies", "documented_unused")


async def _sections_matching(db: AsyncSession, project_id: str, section: str) -> set[str]:
    """Parameter node ids documented in a manual section whose number or title matches ``section``."""
    needle = section.strip().casefold()
    rows = await db.execute(
        select(KnowledgeStructuredNode.node_id, KnowledgeStructuredNode.label).where(
            KnowledgeStructuredNode.project_id == project_id,
            KnowledgeStructuredNode.layer == LAYER_MANUAL,
            KnowledgeStructuredNode.node_type.in_(("Chapter", "Section", "Subsection")),
        )
    )
    sections = {str(row[0]) for row in rows.all() if needle in str(row[1]).casefold()}
    if not sections:
        return set()
    documented = await db.execute(
        select(KnowledgeStructuredEdge.source_id).where(
            KnowledgeStructuredEdge.project_id == project_id,
            KnowledgeStructuredEdge.edge_type == "documented_in",
            KnowledgeStructuredEdge.target_id.in_(sorted(sections)),
        )
    )
    return {str(row[0]) for row in documented.all()}


def _bounded(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()[:MAX_FILTER_CHARS]
    return text or None


async def _layer_state(db: AsyncSession, authorized: AuthorizedWorkspace, profile_id, result: dict) -> bool:
    """Set the report's state and build time; ``False`` when no configuration layer is built yet."""
    layers = dict((await db.execute(
        select(KnowledgeStructuredExtraction.layer, func.count()).where(
            KnowledgeStructuredExtraction.project_id == authorized.project_id,
            KnowledgeStructuredExtraction.profile == profile_id,
        ).group_by(KnowledgeStructuredExtraction.layer)
    )).all())
    if not layers.get(LAYER_CONFIGURATION):
        return False
    if not layers.get(LAYER_MANUAL):
        result["state"] = "no_manual"
    built = (await db.execute(
        select(func.max(KnowledgeStructuredBuild.finished_at)).where(
            KnowledgeStructuredBuild.project_id == authorized.project_id, KnowledgeStructuredBuild.state == "completed"
        )
    )).scalar_one_or_none()
    result["built_at"] = built.isoformat() if built else None
    return True


async def _capped_edges(db: AsyncSession, authorized: AuthorizedWorkspace, profile_id, result: dict) -> list:
    edges = []
    for edge_type in _TYPES:
        cap = MAX_EDGES_PER_TYPE * (MAX_NAME_MATCHES if edge_type == "name_matches" else 1)
        typed = (await db.execute(
            select(KnowledgeStructuredEdge).where(
                KnowledgeStructuredEdge.project_id == authorized.project_id,
                KnowledgeStructuredEdge.layer == LAYER_CONFIGURATION,
                KnowledgeStructuredEdge.revision_id.is_(None),
                KnowledgeStructuredEdge.profile == profile_id,
                KnowledgeStructuredEdge.edge_type == edge_type,
            ).order_by(KnowledgeStructuredEdge.edge_key).limit(cap + 1)
        )).scalars().all()
        if len(typed) > cap:
            result["edges_capped"] = True
        edges.extend(typed[:cap])
    return edges


async def _visible_edges(db: AsyncSession, authorized: AuthorizedWorkspace, edges: list) -> tuple[list, dict]:
    """The edges every cited revision and both ends of which the reader may see, with those nodes."""
    visible = await visible_revisions(db, authorized, {cite[0] for edge in edges for cite in cites_of(edge.citations)})
    edges = [edge for edge in edges if all(cite[0] in visible for cite in cites_of(edge.citations))]
    nodes = await visible_nodes(db, authorized, {e.source_id for e in edges} | {e.target_id for e in edges},
                                visible=visible)
    return [edge for edge in edges if edge.source_id in nodes and edge.target_id in nodes], nodes


async def handbook_vs_reality(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    parameter: object = None,
    file: object = None,
    section: object = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    profile_id = await workspace_profile_id(db, authorized.project_id)
    limit = max(1, min(int(limit), MAX_LIMIT))
    parameter, file, section = _bounded(parameter), _bounded(file), _bounded(section)
    result: dict[str, Any] = {
        "workspace_id": authorized.project_id, "profile": profile_id, "state": "ok",
        "filters": {"parameter": parameter, "file": file, "section": section}, "content_is_data": True,
        "counts": {}, **{name: [] for name in _LISTS}, "truncated": False, "edges_capped": False, "built_at": None,
    }
    if not await _layer_state(db, authorized, profile_id, result):
        return {**result, "state": "not_built"}
    edges = await _capped_edges(db, authorized, profile_id, result)
    edges, nodes = await _visible_edges(db, authorized, edges)
    in_section = await _sections_matching(db, authorized.project_id, section) if section else None
    found = select_findings(edges, nodes, parameter=parameter, file=file, in_section=in_section)
    result["counts"] = found.counts()
    result["truncated"] = result["edges_capped"] or any(result["counts"][name] > limit for name in _LISTS)

    cut = replace(found, undocumented=found.undocumented[:limit], unknown=found.unknown[:limit],
                  deviations=found.deviations[:limit], placeholders=found.placeholders[:limit])
    group_items = sorted(found.groups.items())[:limit]
    unused_items = sorted(found.unused.items(), key=lambda item: nodes[item[0]].label)[:limit]
    citations = await presented_citations(db, authorized, wanted_citations(cut, nodes, group_items, unused_items))
    fill_lists(result, cut, nodes, citations, group_items, unused_items)
    return result


__all__ = ["DEFAULT_LIMIT", "MAX_EDGES_PER_TYPE", "MAX_LIMIT", "handbook_vs_reality"]
