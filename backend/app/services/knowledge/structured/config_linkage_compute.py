"""The configuration linkage as a pure function of the loaded nodes (no database)."""

from __future__ import annotations

from .config_families import Family, NodeRow, Placeholders, families, variant_item
from .config_linkage_rules import (
    MAX_FILES_PER_UNUSED,
    MAX_NAME_MATCHES,
    _cites,
    _file_id,
    _inconsistencies,
    _Scopes,
    _section_key,
    _unknown_sections,
    _value_edges,
    ini_matches,
    scope_covers,
)
from .profile_patterns import ProfilePattern
from .store_types import LinkEdge


def compute_linkage(
    settings: list[NodeRow],
    parameters: list[NodeRow],
    documents: list[NodeRow],
    registry_sections: tuple[str, ...] = (),
    placeholders: Placeholders | None = None,
    non_comparable_defaults: tuple[ProfilePattern, ...] = (),
    fold_resolved_definitions: bool = False,
) -> list[LinkEdge]:
    placeholders = placeholders or Placeholders(settings, None, ())
    resolved = {setting.node_id: placeholders.resolve(setting) for setting in settings}
    # Only a manual that documents parameters can leave a setting undocumented.
    documented = {parameter.revision_id for parameter in parameters}
    manuals = [document for document in documents if document.revision_id in documented]
    grouped = families(settings)
    edges, configured, used_scopes, unknown = _family_edges(
        grouped, parameters, manuals, registry_sections, resolved, non_comparable_defaults
    )
    edges.extend(_unknown_sections(unknown, manuals))
    edges.extend(_documented_unused(grouped, parameters, configured, used_scopes))
    folded = placeholders.definitions if fold_resolved_definitions else frozenset()
    edges.extend(_inconsistencies(grouped, resolved, folded))
    return edges


def _family_edges(
    grouped: list[Family],
    parameters: list[NodeRow],
    manuals: list[NodeRow],
    registry_sections: tuple[str, ...],
    resolved: dict,
    non_comparable_defaults: tuple[ProfilePattern, ...],
) -> tuple[list[LinkEdge], set[str], set[tuple[str, str]], dict[tuple, list[Family]]]:
    scopes = _Scopes(parameters)
    by_name: dict[str, list[NodeRow]] = {}
    for parameter in parameters:
        by_name.setdefault(parameter.properties.get("name") or "", []).append(parameter)
    edges: list[LinkEdge] = []
    configured: set[str] = set()
    used_scopes: set[tuple[str, str]] = set()
    unknown: dict[tuple, list[Family]] = {}
    for family in grouped:
        lead, props = family.lead, family.lead.properties
        # Registry entries (``HttpService_Ping = HttpService(…)``) declare instances; they are no parameters.
        if not props.get("manual_documented") or props.get("section") in registry_sections:
            continue
        candidates = by_name.get(props.get("key") or "", [])
        matched = [(parameter, how) for parameter in candidates if (how := scope_covers(parameter, lead))]
        for parameter, how in matched:
            configured.add(parameter.node_id)
            used_scopes.add((parameter.properties["scope_kind"], parameter.properties["scope"]))
            for member in family.members:
                edges.append(LinkEdge("configures", member.node_id, parameter.node_id,
                                      [member.cite, parameter.cite], {"match": how}))
            edges.extend(_value_edges(family, parameter, resolved, non_comparable_defaults))
        if matched:
            continue
        edges.extend(_unmatched_edges(family, candidates, scopes, manuals, unknown))
    return edges, configured, used_scopes, unknown


def _unmatched_edges(
    family: Family, candidates: list[NodeRow], scopes: _Scopes, manuals: list[NodeRow],
    unknown: dict[tuple, list[Family]],
) -> list[LinkEdge]:
    lead = family.lead
    edges = []
    if scopes.known(lead):
        variants = [variant_item(member) for member in family.variants]
        for document in manuals:
            edges.append(LinkEdge("undocumented", lead.node_id, document.node_id, _cites(family),
                                  {"variants": variants}))
    else:
        unknown.setdefault(_section_key(lead), []).append(family)
    # A name documented under many scopes (``ThreadCount``) is generic: no hint rather than noise.
    for parameter in candidates if len(candidates) <= MAX_NAME_MATCHES else ():
        edges.append(LinkEdge("name_matches", lead.node_id, parameter.node_id, [lead.cite, parameter.cite],
                              {"scope": parameter.properties.get("scope")}))
    return edges


def _documented_unused(
    grouped: list[Family], parameters: list[NodeRow], configured: set[str], used_scopes: set[tuple[str, str]]
) -> list[LinkEdge]:
    leads = [family.lead for family in grouped]
    by_section: dict[str, list[NodeRow]] = {}
    by_type: dict[str, list[NodeRow]] = {}
    for setting in leads:
        if setting.properties.get("manual_documented"):
            by_section.setdefault(setting.properties.get("section") or "", []).append(setting)
            by_type.setdefault(setting.properties.get("section_type") or "", []).append(setting)
    edges = []
    for parameter in parameters:
        kind, scope = parameter.properties.get("scope_kind"), parameter.properties.get("scope")
        if parameter.node_id in configured or (kind, scope) not in used_scopes:
            continue
        if kind == "plugin":
            covered = by_type.get(scope, [])
        else:
            covered = [row for section, rows in by_section.items() if ini_matches(scope, section) for row in rows]
        files: dict[str, NodeRow] = {}
        for setting in covered:
            files.setdefault(_file_id(setting), setting)
        for file_id, setting in sorted(files.items())[:MAX_FILES_PER_UNUSED]:
            edges.append(LinkEdge("documented_unused", parameter.node_id, file_id, [parameter.cite, setting.cite],
                                  {"section": setting.properties.get("section")}))
    return edges


__all__ = ["compute_linkage"]
