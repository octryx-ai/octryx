"""Which linkage edges of the "Handbook vs. reality" report make it into each list, after the filters.

Pure selection over the edges and nodes the report already read and checked for visibility; no
database access. Every list keeps one finding per base file, ordered by setting name and path.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Findings:
    """The report's findings per list, filtered but not yet cut to the limit."""

    hints: dict[str, list] = field(default_factory=dict)
    section_hints: dict[tuple, list] = field(default_factory=dict)
    undocumented: list = field(default_factory=list)
    unknown: list = field(default_factory=list)
    deviations: list = field(default_factory=list)
    placeholders: list = field(default_factory=list)
    groups: dict[str, dict[str, dict]] = field(default_factory=dict)
    unused: dict[str, list] = field(default_factory=dict)
    configured: set = field(default_factory=set)

    def counts(self) -> dict[str, int]:
        return {
            "configured_settings": len(self.configured), "undocumented_in_known_section": len(self.undocumented),
            "unknown_section": len(self.unknown),
            "unknown_section_settings": sum(int((e.properties or {}).get("key_count") or 0) for e in self.unknown),
            "deviations": len(self.deviations), "unresolved_placeholders": len(self.placeholders),
            "inconsistencies": len(self.groups), "documented_unused": len(self.unused),
        }


def order_key(view) -> tuple[str, str]:
    return (view.label, view.properties.get("path") or "")


def value_at(values: object, position: int):
    return values[position] if isinstance(values, list) and len(values) > position else None


def variant_paths(props: dict) -> list[str]:
    """Variant file paths of a finding; an inconsistency holds one variant list per side."""
    items = list(props.get("variants") or ())
    items = [nested for item in items for nested in (item if isinstance(item, list) else [item])]
    paths = [str(item.get("path") or "") for item in items if isinstance(item, dict)]
    return paths + [str(path) for path in props.get("variant_files") or ()]


def section_of(view) -> tuple:
    props = view.properties
    return (props.get("repo"), props.get("base_path") or props.get("path"), props.get("section") or "")


def _keeper(nodes: dict, parameter: str | None, file: str | None, in_section: set[str] | None):
    """The filter every list applies: parameter name, file path part and manual section."""

    def keep(*node_ids: str, edge=None) -> bool:
        views = [nodes[node_id] for node_id in node_ids]
        names = {view.properties.get("key") or view.properties.get("name") for view in views}
        paths = [str(view.properties.get("path") or "") for view in views]
        if edge is not None:
            names.update((edge.properties or {}).get("keys") or ())
            paths += variant_paths(edge.properties or {})
        if parameter and parameter not in names:
            return False
        if file and not any(file in path for path in paths):
            return False
        return in_section is None or any(node_id in in_section for node_id in node_ids)

    return keep


def _sorted_by_setting(edges, nodes: dict) -> list:
    return sorted(edges, key=lambda e: order_key(nodes[e.source_id]))


def _inconsistency_groups(edges, nodes: dict, keep) -> dict[str, dict[str, dict]]:
    groups: dict[str, dict[str, dict]] = {}
    for edge in edges:
        if keep(edge.source_id, edge=edge) or keep(edge.target_id, edge=edge):
            props = edge.properties or {}
            members = groups.setdefault(nodes[edge.source_id].label, {})
            for position, member in enumerate((edge.source_id, edge.target_id)):
                members.setdefault(member, {"value": value_at(props.get("values"), position),
                                            "variants": value_at(props.get("variants"), position) or []})
    return groups


def select_findings(
    edges, nodes: dict, *, parameter: str | None, file: str | None, in_section: set[str] | None
) -> Findings:
    keep = _keeper(nodes, parameter, file, in_section)
    by_type: dict[str, list] = {}
    for edge in edges:
        by_type.setdefault(edge.edge_type, []).append(edge)
    found = Findings()
    hints = found.hints
    for edge in by_type.get("name_matches", []):
        hints.setdefault(edge.source_id, []).append(edge)
    found.undocumented = _sorted_by_setting({
        e.source_id: e for e in by_type.get("undocumented", [])
        if keep(e.source_id, *[h.target_id for h in hints.get(e.source_id, [])], edge=e)
    }.values(), nodes)
    for source_id, items in hints.items():
        found.section_hints.setdefault(section_of(nodes[source_id]), []).extend(items)

    def section_hint_ids(edge) -> list[str]:
        return [hint.target_id for hint in found.section_hints.get(section_of(nodes[edge.source_id]), [])]

    found.unknown = _sorted_by_setting({e.source_id: e for e in by_type.get("unknown_section", [])
                                        if keep(e.source_id, *section_hint_ids(e), edge=e)}.values(), nodes)
    found.deviations = _sorted_by_setting([e for e in by_type.get("deviates_from_default", [])
                                           if keep(e.source_id, e.target_id, edge=e)], nodes)
    found.placeholders = _sorted_by_setting([e for e in by_type.get("unresolved_placeholder", [])
                                             if keep(e.source_id, e.target_id, edge=e)], nodes)
    found.groups = _inconsistency_groups(by_type.get("inconsistent_across", []), nodes, keep)
    for edge in by_type.get("documented_unused", []):
        if keep(edge.source_id, edge.target_id):
            found.unused.setdefault(edge.source_id, []).append(edge)
    found.configured = {e.source_id for e in by_type.get("configures", []) if keep(e.source_id, e.target_id)}
    return found


__all__ = ["Findings", "order_key", "section_of", "select_findings", "value_at", "variant_paths"]
