"""The outline of a manual and its cross-references, from span headings alone."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .facts import Extraction, NodeRef, SpanInput, SpanRef, clip
from .profile_types import StructuredProfile

_NUMBERED = re.compile(r"^(\d+(?:\.\d+)+|\d+)\s+(\S.*)$")
_IDENTIFIER = re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+$")
MAX_FOLDED_HEADINGS = 20
MAX_REFERENCES_PER_SECTION = 60
NODE_DOCUMENT = "Document"
EDGE_CONTAINS = "contains"
EDGE_REFERENCES = "references"


def is_identifier(text: str) -> bool:
    return bool(_IDENTIFIER.fullmatch(text))


def node_type_for(level: int) -> str:
    return "Chapter" if level == 1 else "Section" if level == 2 else "Subsection"


@dataclass(slots=True)
class Section:
    key: str
    number: str | None
    title: str
    level: int
    parent: str | None
    first_span: int
    page_start: int | None = None
    page_end: int | None = None
    plugin: str | None = None
    headings: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.number} {self.title}" if self.number else self.title


@dataclass(slots=True)
class Outline:
    document_key: str
    sections: dict[str, Section] = field(default_factory=dict)
    # Span ordinal -> the section it belongs to (``None``: front matter of the document).
    span_section: dict[int, str | None] = field(default_factory=dict)

    def section_of(self, ordinal: int) -> Section | None:
        key = self.span_section.get(ordinal)
        return self.sections.get(key) if key else None

    def chain(self, key: str | None) -> list[Section]:
        found = []
        while key:
            section = self.sections[key]
            found.append(section)
            key = section.parent
        return found

    def at_page(self, page: int) -> Section | None:
        starting = [s for s in self.sections.values() if s.page_start == page]
        if starting:
            return min(starting, key=lambda section: section.level)
        best: Section | None = None
        for section in self.sections.values():
            if section.page_start is not None and section.page_start <= page <= (section.page_end or page):
                if best is None or section.level > best.level:
                    best = section
        return best


class _Builder:
    def __init__(self, profile: StructuredProfile, document_key: str) -> None:
        self.profile = profile
        self.outline = Outline(document_key)
        self.current: str | None = None
        self.last_number: tuple[int, ...] | None = None
        # The latest folded heading since the last numbered one: a chapter title candidate.
        self.pending: tuple[str, int, str | None] | None = None

    def _ignored(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in self.profile.ignored_headings)

    def _add(self, key: str, number: str | None, title: str, level: int, parent: str | None, first: int) -> str:
        if key not in self.outline.sections:
            self.outline.sections[key] = Section(key, number, clip(title, 200), level, parent, first)
        return key

    def _numbered(self, number: tuple[int, ...], title: str, ordinal: int) -> None:
        doc = self.outline.document_key
        sections = self.outline.sections
        missing = [depth for depth in range(1, len(number)) if f"{doc}#{self._label(number[:depth])}" not in sections]
        parent: str | None = None
        for depth in range(1, len(number)):
            prefix = self._label(number[:depth])
            key = f"{doc}#{prefix}"
            if key not in self.outline.sections:
                implied = f"Chapter {prefix}" if depth == 1 else f"Section {prefix}"
                first = ordinal
                if depth == missing[-1] and self.pending is not None:
                    # The closest implied ancestor takes the heading right before it as its title,
                    # together with that heading's spans.
                    implied, first, owner = self.pending
                    if owner is not None and implied in self.outline.sections[owner].headings:
                        self.outline.sections[owner].headings.remove(implied)
                    for span in list(self.outline.span_section):
                        if span >= first:
                            self.outline.span_section[span] = key
                self._add(key, prefix, implied, depth, parent, first)
            parent = key
        label = self._label(number)
        self.current = self._add(f"{doc}#{label}", label, title, len(number), parent, ordinal)
        self.last_number = number
        self.pending = None

    @staticmethod
    def _label(number: tuple[int, ...]) -> str:
        return ".".join(map(str, number))

    def heading(self, text: str, ordinal: int) -> None:
        text = " ".join(text.split())
        if not text or self._ignored(text):
            return
        match = _NUMBERED.match(text)
        if match:
            number = tuple(int(part) for part in match.group(1).split("."))
            last = self.last_number
            if last is None or (number > last and (len(number) > 1 or number[0] <= last[0] + 1)):
                self._numbered(number, match.group(2), ordinal)
                return
        anchor = self._numbered_anchor()
        if is_identifier(text):
            parent = self.outline.sections.get(anchor) if anchor else None
            key = f"{anchor or self.outline.document_key + '#'}/{text}"
            if key in self.outline.sections:
                key = f"{key}@{ordinal}"
            level = (parent.level + 1) if parent else 1
            self._add(key, None, text, level, anchor, ordinal)
            self.outline.sections[key].plugin = text
            self.current = key
            return
        if self.current is not None:
            headings = self.outline.sections[self.current].headings
            if text not in headings and len(headings) < MAX_FOLDED_HEADINGS:
                headings.append(text)
        self.pending = (text, ordinal, self.current)

    def _numbered_anchor(self) -> str | None:
        key = self.current
        while key and self.outline.sections[key].number is None:
            key = self.outline.sections[key].parent
        return key

    def assign(self, span: SpanInput) -> None:
        self.outline.span_section[span.ordinal] = self.current

    def finish(self, spans: list[SpanInput]) -> Outline:
        pages = {span.ordinal: span for span in spans}
        for ordinal, key in self.outline.span_section.items():
            span = pages[ordinal]
            for section in self.outline.chain(key):
                if span.page_start is not None:
                    start, end = span.page_start, span.page_end or span.page_start
                    section.page_start = start if section.page_start is None else min(section.page_start, start)
                    section.page_end = end if section.page_end is None else max(section.page_end, end)
        return self.outline


def build_outline(spans: list[SpanInput], profile: StructuredProfile, document_key: str) -> Outline:
    builder = _Builder(profile, document_key)
    previous: str | None = None
    for span in spans:
        leaf = span.leaf_heading
        if leaf is not None and leaf != previous:
            builder.heading(leaf, span.ordinal)
        previous = leaf
        builder.assign(span)
    return builder.finish(spans)


def section_ref(outline: Outline, key: str | None) -> NodeRef:
    if key is None:
        return NodeRef(NODE_DOCUMENT, outline.document_key)
    return NodeRef(node_type_for(outline.sections[key].level), key)


def add_outline(extraction: Extraction, outline: Outline, title: str, first_span: int | None) -> None:
    cite = SpanRef(first_span) if first_span is not None else None
    extraction.node(NODE_DOCUMENT, outline.document_key, title, cite, kind="manual")
    for section in outline.sections.values():
        ref = extraction.node(
            node_type_for(section.level), section.key, section.label, SpanRef(section.first_span),
            number=section.number, title=section.title, level=section.level, page_start=section.page_start,
            page_end=section.page_end, plugin=section.plugin, headings=list(section.headings),
        )
        extraction.edge(EDGE_CONTAINS, section_ref(outline, section.parent), ref, SpanRef(section.first_span))


def _by_title(outline: Outline) -> dict[str, list[Section]]:
    titles: dict[str, list[Section]] = {}
    for section in outline.sections.values():
        for name in (section.title, *section.headings):
            titles.setdefault(name, []).append(section)
    return titles


def _resolve(outline: Outline, titles, kind: str, groups: tuple[str, ...]) -> Section | None:
    if kind == "section":
        return outline.sections.get(f"{outline.document_key}#{groups[0]}")
    page = int(groups[-1])
    if kind == "named_page":
        named = titles.get(groups[0].strip(), [])
        covering = [s for s in named if s.page_start is not None and s.page_start <= page <= (s.page_end or page)]
        if covering:
            return covering[0]
    # The page is authoritative: a name that no section on that page carries does not override it.
    return outline.at_page(page)


def add_references(extraction: Extraction, outline: Outline, spans: list[SpanInput], profile: StructuredProfile):
    titles = _by_title(outline)
    counts: dict[str | None, int] = {}
    for span in spans:
        origin_key = outline.span_section.get(span.ordinal)
        for reference in profile.reference_patterns:
            for match in reference.pattern.finditer(span.text):
                if counts.get(origin_key, 0) >= MAX_REFERENCES_PER_SECTION:
                    extraction.warn("references_truncated")
                    break
                target = _resolve(outline, titles, reference.kind, match.groups())
                if target is None:
                    extraction.warn("reference_unresolved")
                    continue
                if target.key == origin_key:
                    continue
                before = len(extraction.edges)
                extraction.edge(
                    EDGE_REFERENCES, section_ref(outline, origin_key), section_ref(outline, target.key),
                    SpanRef(span.ordinal), anchor=clip(match.group(0), 120),
                )
                if len(extraction.edges) > before:
                    counts[origin_key] = counts.get(origin_key, 0) + 1


__all__ = [
    "EDGE_CONTAINS",
    "EDGE_REFERENCES",
    "NODE_DOCUMENT",
    "Outline",
    "Section",
    "add_outline",
    "add_references",
    "build_outline",
    "is_identifier",
    "node_type_for",
    "section_ref",
]
