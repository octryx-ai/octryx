"""One readable sentence per structured edge, built only from the edge's own typed properties."""

from __future__ import annotations

from typing import Any

_VERBS = {
    "contains": "contains",
    "references": "references",
    "documented_in": "is documented in",
    "requires": "requires",
    "supports": "supports",
    "mentions": "mentions",
    "similar_to": "is similar to",
    "row_of": "has the table row",
    "defines": "defines",
    "configures": "configures",
    "changes_file": "changed",
    "deviates_from_default": "deviates from the documented default of",
    "undocumented": "is not documented in",
    "unknown_section": "opens a section unknown to",
    "unresolved_placeholder": "has an unresolved placeholder instead of the documented default of",
    "name_matches": "shares its name with",
    "documented_unused": "is never set in",
    "inconsistent_across": "differs from",
    "assigned_to_group": "is assigned to",
    "affects_service": "affects the service",
    "affects_ci": "affects the configuration item",
    "caused_by": "was caused by",
    "in_component": "is in the component",
    "released_in": "is released in",
    "affects_version": "affects the version",
    "runs_in": "runs in",
    "uses_image": "uses the image",
}


def describe(edge_type: str, source: str, target: str, properties: dict[str, Any] | None = None) -> str:
    props = properties or {}
    sentence = f"{source} {_VERBS.get(edge_type, edge_type.replace('_', ' '))} {target}"
    if edge_type in ("requires", "supports") and props.get("versions"):
        sentence += f" {props['versions']}"
    elif edge_type == "deviates_from_default":
        unit = f" {props['unit']}" if props.get("unit") else ""
        sentence += f": value {props.get('value')}{unit}, documented default {props.get('default')}{unit}"
    elif edge_type == "inconsistent_across" and props.get("values"):
        left, right = (props.get("components") or ["?", "?"])[:2]
        sentence += f": {left} {props['values'][0]} vs {right} {props['values'][1]}"
    elif edge_type == "unknown_section":
        section = f"[{props['section']}]" if props.get("section") else "the file"
        sentence += f": {section} with {props.get('key_count') or 0} keys"
    elif edge_type == "similar_to" and props.get("score") is not None:
        sentence += f" (score {props['score']})"
    elif edge_type == "configures" and props.get("match"):
        sentence += f" (by {props['match'].replace('_', ' ')})"
    return sentence


__all__ = ["describe"]
