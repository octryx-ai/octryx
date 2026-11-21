"""Configured settings against documented parameters, and settings against each other.

All rules are exact and case-sensitive; nothing is matched by similarity. Settings are judged per
variant family (:mod:`.config_families`): a finding is stated once, on the family's lead (the base
file's setting), and its edge lists the variants (``app.ini-test``) with their values.

- ``configures`` (setting → parameter): same key name, and the parameter's scope covers the
  setting's section: its INI pattern (``GeneralSettings`` exactly, ``Cache?`` = a section starting
  with ``Cache``) or its plugin type equals the section's type (``[HttpService_Ping]`` is an
  ``HttpService`` by the ``[Services]`` registry). ``<Source>``-style patterns match nothing.
  Stated for every member of a family (a fact, not a finding).
- ``deviates_from_default`` (lead → parameter): configured, and a member's readable value differs
  from the documented default (numbers compare numerically, ``true``/``false`` without case). A
  placeholder value (``${Name}``) is compared only after it resolved from the profile's placeholder
  sources; the edge then keeps the raw value and cites the definition.
  A documented default the profile marks as no value (``non_comparable_defaults``: ``<Format>``,
  ``{BaseDir}+"/incoming"``, prose) is never compared.
- ``unresolved_placeholder`` (lead → parameter): configured, and a member's value holds a
  placeholder no source resolves. It is never compared with the default.
- ``undocumented`` (lead → each manual with parameters): no parameter configures it, but the
  manual documents the setting's section (some parameter's scope covers it): the important case,
  a key the manual should know. ``name_matches`` (setting → parameter) then names every same-name
  parameter of another scope (at most five; a more generic name gets none).
- ``unknown_section`` (first lead of the section → each manual with parameters): the manual
  documents nothing of the section at all (``[HttpRequestCardIds]``, a sectionless properties
  file); one edge per repository, base file and section, with the key count and the keys (capped).
  Its keys still get ``name_matches`` hints.
  Undocumented and unknown sections are judged only for file kinds the profile marks as
  manual-documented (INI, properties, not logging/framework files or placeholder sources).
  Registry entries (``[Services]``, ``[Provider]``) declare instances and are never judged.
- ``documented_unused`` (parameter → file): never configured, although some parameter of the same
  scope is configured; one edge per file that has a section of that scope (variants fold into
  their base file).
- ``inconsistent_across`` (lead ↔ lead): the same format, section and key in different
  components with different readable (resolved) values (``conf`` 500 vs ``data`` 60000), one edge per
  differing pair. An unresolved placeholder is never compared. With the profile switch
  ``fold_resolved_definitions`` (on by default) a pair of placeholder *definitions*
  (``Dec_ThreadCount`` in two components' ``*_config.properties``) is not stated when a pair of
  settings that resolve from exactly those two definitions already differs: the difference is
  reported once, on the settings, which cite the definition lines. A definition pair no differing
  setting pair resolves from is still stated.

Redacted values are never compared. Every edge is cited from the setting's line, the lines of its
variants and placeholder definitions and, where a parameter is involved, the parameter's table span.
"""

from __future__ import annotations

from sqlalchemy import select

from ....models.project.knowledge_structured import KnowledgeStructuredNode
from .config_families import NodeRow, Placeholders, families
from .config_linkage_compute import compute_linkage
from .config_linkage_rules import _inconsistencies
from .profile_types import LAYER_CONFIGURATION, LAYER_MANUAL
from .store import sync_linkage


async def load_nodes(db, project_id: str, profile_id: str, layer: str, node_types: tuple[str, ...]) -> list[NodeRow]:
    rows = await db.execute(
        select(
            KnowledgeStructuredNode.node_id, KnowledgeStructuredNode.node_type, KnowledgeStructuredNode.revision_id,
            KnowledgeStructuredNode.span_ordinal, KnowledgeStructuredNode.line, KnowledgeStructuredNode.label,
            KnowledgeStructuredNode.properties,
        )
        .where(
            KnowledgeStructuredNode.project_id == project_id,
            KnowledgeStructuredNode.profile == profile_id,
            KnowledgeStructuredNode.layer == layer,
            KnowledgeStructuredNode.node_type.in_(node_types),
        )
        .order_by(KnowledgeStructuredNode.node_id, KnowledgeStructuredNode.revision_id)
    )
    return [NodeRow(str(r[0]), r[1], str(r[2]), r[3], r[4], r[5], dict(r[6] or {})) for r in rows.all()]


async def link_configuration(context) -> dict:
    profile_id = context.profile.profile_id
    settings = await load_nodes(
        context.db, context.project_id, profile_id, LAYER_CONFIGURATION, ("ConfiguredSetting",)
    )
    parameters = await load_nodes(context.db, context.project_id, profile_id, LAYER_MANUAL, ("Parameter",))
    documents = await load_nodes(context.db, context.project_id, profile_id, LAYER_MANUAL, ("Document",))
    profile = context.profile
    placeholders = Placeholders(settings, profile.placeholder_pattern, profile.placeholder_sources)
    if parameters:
        desired = compute_linkage(settings, parameters, documents, profile.registry_sections, placeholders,
                                  profile.non_comparable_defaults, profile.fold_resolved_definitions)
    else:
        resolved = {setting.node_id: placeholders.resolve(setting) for setting in settings}
        folded = placeholders.definitions if profile.fold_resolved_definitions else frozenset()
        desired = _inconsistencies(families(settings), resolved, folded)
    counts = await sync_linkage(
        context.db, project_id=context.project_id, layer=LAYER_CONFIGURATION, profile_id=profile_id, desired=desired
    )
    by_type: dict[str, int] = {}
    for edge in desired:
        by_type[edge.edge_type] = by_type.get(edge.edge_type, 0) + 1
    return {
        "state": "ok" if parameters else "no_manual_parameters", "settings": len(settings),
        "parameters": len(parameters), "edges": dict(sorted(by_type.items())), "added": counts.edges,
        "removed": counts.removed_edges,
    }


__all__ = [
    "link_configuration",
    "load_nodes",
]
