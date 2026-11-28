"""The matching rules and edge builders behind :func:`.config_linkage.compute_linkage`."""

from __future__ import annotations

from .config_families import Family, NodeRow, Resolved, variant_item
from .facts import node_id
from .profile_patterns import ProfilePattern
from .store_types import LinkEdge

MAX_PAIRS_PER_KEY = 45
MAX_FILES_PER_UNUSED = 10
MAX_NAME_MATCHES = 5
MAX_SECTION_KEYS = 200
_BOOLEANS = frozenset({"true", "false"})


def same_value(left: str, right: str) -> bool:
    left, right = left.strip(), right.strip()
    if left == right:
        return True
    if left.casefold() in _BOOLEANS and right.casefold() in _BOOLEANS:
        return left.casefold() == right.casefold()
    try:
        return float(left) == float(right)
    except ValueError:
        return False


def ini_matches(pattern: str, section: str | None) -> bool:
    if not section or (pattern.startswith("<") and pattern.endswith(">")):
        return False
    if pattern.endswith("?"):
        return section.startswith(pattern[:-1]) and len(section) >= len(pattern) - 1
    return section == pattern


def scope_covers(parameter: NodeRow, setting: NodeRow) -> str | None:
    kind, scope = parameter.properties.get("scope_kind"), parameter.properties.get("scope")
    if kind == "ini" and scope and ini_matches(scope, setting.properties.get("section")):
        return "ini_section"
    if kind == "plugin" and scope and scope == setting.properties.get("section_type"):
        return "plugin_type"
    return None


def _file_id(setting: NodeRow) -> str:
    return node_id("ConfigFile", f"{setting.properties['repo']}:{setting.properties['path']}")


class _Scopes:
    def __init__(self, parameters: list[NodeRow]) -> None:
        self.ini = sorted({p.properties["scope"] for p in parameters
                           if p.properties.get("scope_kind") == "ini" and p.properties.get("scope")})
        self.plugin = {p.properties["scope"] for p in parameters
                       if p.properties.get("scope_kind") == "plugin" and p.properties.get("scope")}

    def known(self, setting: NodeRow) -> bool:
        props = setting.properties
        if props.get("section_type") and props["section_type"] in self.plugin:
            return True
        return any(ini_matches(pattern, props.get("section")) for pattern in self.ini)


def _cites(family: Family, *extra: tuple, resolved: list[Resolved] = ()) -> list[tuple]:
    cites = [member.cite for member in family.members] + list(extra)
    cites += [source.cite for item in resolved for source in item.sources]
    return list(dict.fromkeys(cites))


def _value_edges(
    family: Family, parameter: NodeRow, resolved: dict[str, Resolved], non_comparable: tuple[ProfilePattern, ...]
) -> list[LinkEdge]:
    default = parameter.properties.get("default")
    readable = [member for member in family.members if not member.properties.get("redacted")]
    if default is None or not readable or any(pattern.search(default) for pattern in non_comparable):
        return []
    deviates = {m.node_id: resolved[m.node_id].value is not None and not same_value(resolved[m.node_id].value, default)
                for m in readable}
    unresolved = [m for m in readable if resolved[m.node_id].value is None]
    lead, lead_value = family.lead, resolved[family.lead.node_id]
    variants = [variant_item(m, resolved[m.node_id], deviates=deviates.get(m.node_id, False),
                             unresolved=list(resolved[m.node_id].unresolved)) for m in family.variants]
    edges = []
    if any(deviates.values()):
        properties = {"value": lead.properties.get("value"), "default": default,
                      "unit": parameter.properties.get("unit"), "deviates": deviates.get(lead.node_id, False),
                      "variants": variants}
        if lead_value.substituted and lead_value.value is not None:
            properties["resolved_value"] = lead_value.value
        used = [resolved[m.node_id] for m in readable if resolved[m.node_id].value is not None]
        edges.append(LinkEdge("deviates_from_default", lead.node_id, parameter.node_id,
                              _cites(family, parameter.cite, resolved=used), properties))
    if unresolved:
        edges.append(LinkEdge("unresolved_placeholder", lead.node_id, parameter.node_id,
                              _cites(family, parameter.cite),
                              {"value": lead.properties.get("value"), "default": default,
                               "unit": parameter.properties.get("unit"),
                               "placeholders": list(dict.fromkeys(n for m in unresolved
                                                                  for n in resolved[m.node_id].unresolved)),
                               "variants": variants}))
    return edges


def _section_key(setting: NodeRow) -> tuple:
    props = setting.properties
    return (props.get("repo"), props.get("base_path") or props.get("path"), props.get("section") or "")


def _unknown_sections(unknown: dict[tuple, list[Family]], manuals: list[NodeRow]) -> list[LinkEdge]:
    edges = []
    for (_, _, section), members in unknown.items():
        members = sorted(members, key=lambda family: (family.lead.line or 0, family.lead.node_id))
        first = members[0].lead
        keys = [family.lead.properties.get("key") for family in members]
        # Variant files of the section: variants of a base key, and keys only a variant file has.
        variants = sorted({row.properties.get("path") for family in members for row in family.members
                           if row.properties.get("variant")})
        properties = {"section": section or None, "key_count": len(keys), "keys": keys[:MAX_SECTION_KEYS],
                      "variant_files": variants}
        for document in manuals:
            edges.append(LinkEdge("unknown_section", first.node_id, document.node_id, [first.cite], properties))
    return edges


def _inconsistencies(
    grouped: list[Family], resolved: dict[str, Resolved] | None = None, definitions: frozenset[str] = frozenset()
) -> list[LinkEdge]:
    resolved = resolved or {}
    groups: dict[tuple, list[Family]] = {}
    for family in grouped:
        props = family.lead.properties
        if props.get("redacted"):
            continue
        groups.setdefault((props.get("format"), props.get("section"), props.get("key")), []).append(family)
    edges = []
    for group in groups.values():
        pairs = 0
        ordered = sorted(group, key=lambda family: family.lead.node_id)
        for index, left_family in enumerate(ordered):
            left = left_family.lead
            for right_family in ordered[index + 1 :]:
                right = right_family.lead
                if left.properties.get("component") == right.properties.get("component"):
                    continue
                values = [_comparable(left, resolved), _comparable(right, resolved)]
                if None in values or same_value(*values):
                    continue
                if pairs >= MAX_PAIRS_PER_KEY:
                    break
                pairs += 1
                edges.append(LinkEdge(
                    "inconsistent_across", left.node_id, right.node_id,
                    list(dict.fromkeys(_cites(left_family) + _cites(right_family)
                                       + [s.cite for row in (left, right) for s in _sources(row, resolved)])),
                    {"values": values,
                     "raw_values": [left.properties.get("value"), right.properties.get("value")],
                     "components": [left.properties.get("component"), right.properties.get("component")],
                     "variants": [[variant_item(v) for v in left_family.variants],
                                  [variant_item(v) for v in right_family.variants]]},
                ))
    if not definitions:
        return edges
    reported = {
        frozenset((left.node_id, right.node_id))
        for edge in edges if not {edge.source_id, edge.target_id} & definitions
        for left in _sources_of(edge.source_id, resolved) for right in _sources_of(edge.target_id, resolved)
    }
    return [edge for edge in edges if not ({edge.source_id, edge.target_id} <= definitions
                                           and frozenset((edge.source_id, edge.target_id)) in reported)]


def _sources_of(node_id: str, resolved: dict[str, Resolved]) -> tuple[NodeRow, ...]:
    found = resolved.get(node_id)
    return found.sources if found is not None else ()


def _comparable(setting: NodeRow, resolved: dict[str, Resolved]) -> str | None:
    found = resolved.get(setting.node_id)
    return found.value if found is not None else str(setting.properties.get("value") or "")


def _sources(setting: NodeRow, resolved: dict[str, Resolved]) -> tuple[NodeRow, ...]:
    found = resolved.get(setting.node_id)
    return found.sources if found is not None else ()


__all__ = [
    "MAX_FILES_PER_UNUSED",
    "MAX_NAME_MATCHES",
    "MAX_PAIRS_PER_KEY",
    "MAX_SECTION_KEYS",
    "ini_matches",
    "same_value",
    "scope_covers",
]
