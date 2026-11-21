"""The items of the "Handbook vs. reality" report: each finding as served, with its citations."""

from __future__ import annotations

from typing import Any

from .config_report_findings import Findings, section_of
from .read import cites_of


def setting_item(view, citation) -> dict[str, Any]:
    props = view.properties
    return {
        "setting": view.label, "section": props.get("section"), "key": props.get("key"),
        "value": props.get("value"), "redacted": bool(props.get("redacted")), "component": props.get("component"),
        "file": props.get("path"), "repository": props.get("repo"), "line": props.get("line"), "citation": citation,
    }


def parameter_item(view, citation) -> dict[str, Any]:
    props = view.properties
    return {
        "parameter": view.label, "name": props.get("name"), "scope": props.get("scope"),
        "default": props.get("default"), "unit": props.get("unit"), "citation": citation,
    }


def section_item(view, citation, props: dict) -> dict[str, Any]:
    setting = view.properties
    return {
        "section": props.get("section"), "keys": props.get("keys") or [], "key_count": props.get("key_count") or 0,
        "variant_files": props.get("variant_files") or [], "component": setting.get("component"),
        "file": setting.get("path"), "repository": setting.get("repo"), "line": setting.get("line"),
        "citation": citation,
    }


def parameter_cite(edge, nodes) -> tuple | None:
    """The parameter's citation among the edge's (setting, variants, parameter, placeholder definitions)."""
    target = nodes[edge.target_id]
    return target.cite if target.cite in cites_of(edge.citations) else cites_of(edge.citations)[-1]


def wanted_citations(found: Findings, nodes: dict, group_items: list, unused_items: list) -> list:
    """Every citation the cut lists show, in the order the report asks for them."""
    undocumented, unknown, hints, section_hints = found.undocumented, found.unknown, found.hints, found.section_hints
    listed = (*undocumented, *unknown, *found.deviations, *found.placeholders)
    wanted = [c for e in listed for c in cites_of(e.citations)]
    wanted += [nodes[h.target_id].cite for e in undocumented for h in hints.get(e.source_id, [])
               if nodes[h.target_id].cite]
    wanted += [nodes[h.target_id].cite for e in unknown for h in section_hints.get(section_of(nodes[e.source_id]), [])
               if nodes[h.target_id].cite]
    wanted += [nodes[n].cite for _, members in group_items for n in members if nodes[n].cite]
    wanted += [c for _, items in unused_items for e in items for c in cites_of(e.citations)]
    return wanted


def _setting_lists(result: dict, found: Findings, nodes: dict, citations: dict, hint_items) -> None:
    def finding(edge) -> dict[str, Any]:
        props = edge.properties or {}
        item = {**setting_item(nodes[edge.source_id], citations.get(cites_of(edge.citations)[0])),
                "variants": props.get("variants") or []}
        if props.get("resolved_value") is not None:
            item["resolved_value"] = props["resolved_value"]
        return item

    result["undocumented_in_known_section"] = [
        {**finding(e), "name_matches": hint_items(found.hints.get(e.source_id, []))} for e in found.undocumented
    ]
    result["unknown_section"] = [
        {**section_item(nodes[e.source_id], citations.get(cites_of(e.citations)[0]), e.properties or {}),
         "name_matches": hint_items(found.section_hints.get(section_of(nodes[e.source_id]), []))}
        for e in found.unknown
    ]
    result["deviations"] = [
        {**finding(e), "deviates": bool((e.properties or {}).get("deviates", True)),
         "documented": parameter_item(nodes[e.target_id], citations.get(parameter_cite(e, nodes)))}
        for e in found.deviations
    ]
    result["unresolved_placeholders"] = [
        {**finding(e), "placeholders": (e.properties or {}).get("placeholders") or [],
         "documented": parameter_item(nodes[e.target_id], citations.get(parameter_cite(e, nodes)))}
        for e in found.placeholders
    ]


def fill_lists(
    result: dict, found: Findings, nodes: dict, citations: dict, group_items: list, unused_items: list
) -> None:
    """Write the served lists into ``result``; ``found`` holds the lists already cut to the limit."""

    def cited(view) -> dict | None:
        return citations.get(view.cite) if view.cite else None

    def hint_items(items) -> list[dict]:
        return [parameter_item(nodes[h.target_id], cited(nodes[h.target_id])) for h in items]

    _setting_lists(result, found, nodes, citations, hint_items)
    result["inconsistencies"] = [
        {"setting": label, "values": [
            {**setting_item(nodes[n], cited(nodes[n])), "compared_value": members[n]["value"],
             "variants": members[n]["variants"]}
            for n in sorted(members, key=lambda m: nodes[m].properties.get("path") or "")]}
        for label, members in group_items
    ]
    result["documented_unused"] = [
        {**parameter_item(nodes[p], citations.get(cites_of(items[0].citations)[0])),
         "files": sorted({nodes[e.target_id].properties.get("path") or nodes[e.target_id].label for e in items})}
        for p, items in unused_items
    ]


__all__ = ["fill_lists", "parameter_item", "section_item", "setting_item", "wanted_citations"]
