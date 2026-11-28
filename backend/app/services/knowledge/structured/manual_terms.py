"""Technical terms a manual section mentions, from a gazetteer plus pattern rules."""

from __future__ import annotations

import re

from .facts import Extraction, NodeRef, SpanInput, SpanRef
from .manual_structure import Outline, is_identifier, section_ref
from .profile_types import StructuredProfile

_CAMEL = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+\b")


def _gazetteer(extraction: Extraction, outline: Outline) -> dict[str, str]:
    terms: dict[str, str] = {}
    for ref, node in extraction.nodes.items():
        if ref.node_type == "Parameter":
            name = node.properties.get("name") or ""
            if is_identifier(name):
                terms.setdefault(name, "parameter")
    for section in outline.sections.values():
        if section.plugin:
            terms[section.plugin] = "plugin"
    return terms


def add_terms(extraction: Extraction, spans: list[SpanInput], outline: Outline, profile: StructuredProfile) -> None:
    gazetteer = _gazetteer(extraction, outline)
    suffixes = tuple(profile.term_suffixes)
    components = [
        (component, re.compile(rf"(?<![\w-]){re.escape(component.name)}(?![\w-])")) for component in profile.components
    ]
    seen: dict[str | None, set[str]] = {}
    for span in spans:
        if span.kind == "table":
            # Parameter tables would make every row name a mention of its own section.
            continue
        section_key = outline.span_section.get(span.ordinal)
        found = seen.setdefault(section_key, set())
        if len(found) >= profile.max_terms_per_section:
            continue
        origin = section_ref(outline, section_key)
        cite = SpanRef(span.ordinal)
        for match in _CAMEL.finditer(span.text):
            word = match.group(0)
            kind = gazetteer.get(word) or ("class" if word.endswith(suffixes) else None)
            if kind is None or word in found or len(found) >= profile.max_terms_per_section:
                continue
            found.add(word)
            term = extraction.node("Term", f"term:{word}", word, cite, kind=kind)
            extraction.edge("mentions", origin, term, cite)
        for component, pattern in components:
            key = f"component:{component.folded}"
            if key in found or len(found) >= profile.max_terms_per_section or not pattern.search(span.text):
                continue
            found.add(key)
            target = NodeRef("Component", key)
            if target not in extraction.nodes:
                extraction.node("Component", key, component.name, cite, name=component.name)
            extraction.edge("mentions", origin, target, cite)


__all__ = ["add_terms"]
