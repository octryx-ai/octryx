"""Parameter and compatibility tables of a manual, by header semantics.

Docling renders a table as its own span, one ``cell | cell`` row per line. A table that crosses a
page continues in later spans **without** its header, separated only by page-continuation text
(``Table 31 – continued from previous page``). :func:`logical_tables` stitches those spans back into
one table under the header that opened it, inside the same section. A table span that opens with an
unrecognized row and does not continue an open table is not read.

**Parameter tables** have a name column (``Parameter``, optionally prefixed with the INI section
pattern: ``[Cache?] Parameter``) and a ``Default`` column. A row with an empty name continues the
previous parameter's description. A parameter's scope is the header's INI section pattern, else the
plugin that the enclosing heading names (``CacheProvider`` › ``Configuration``), else none.

**Compatibility tables** have a product column first and at least two columns whose header is a
profile component (``Java SE``, ``Post-greSQL``). A header cell that Docling merged from several
components (``Tom- cat My- SQL``) is split only when its value has exactly as many tokens; an
ambiguous column yields no edge, and its row is kept as a ``TableRow`` node instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .facts import Extraction, NodeRef, SpanInput, SpanRef, clip
from .manual_structure import Outline, is_identifier, section_ref
from .profile_types import Component, StructuredProfile, fold

_SECTION_PREFIX = re.compile(r"^\[([^\]]{1,80})\]\s*(.*)$")
_NAME = re.compile(r"^[A-Za-z_$][\w.$\-{}]*$")
_VERSION = re.compile(r"^\d+(?:\.\d+)+[a-z]?$")
_SOFT_HYPHEN = re.compile(r"(?<=[A-Za-z])-\s*(?=[A-Za-z])")
_DIGIT_HYPHEN = re.compile(r"(?<=\d)\s*-\s+(?=\d)")
_UNIT = re.compile(r"\bin (milliseconds|seconds|minutes|hours|bytes)\b", re.IGNORECASE)
_EMPTY_VALUES = frozenset({"", "-", "–", "n/a", "no", "none"})
MANDATORY = "<mandatory>"


def dehyphenate(text: str) -> str:
    """Repair Docling's line-break hyphens (``Post-greSQL`` -> ``PostgreSQL``, ``2019- 2022`` -> ``2019-2022``)."""
    return _DIGIT_HYPHEN.sub("-", _SOFT_HYPHEN.sub("", " ".join(text.split())))


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.split("|")]


@dataclass(slots=True)
class LogicalTable:
    header: list[str]
    section: str | None
    rows: list[tuple[list[str], int]] = field(default_factory=list)


def _is_filler(span: SpanInput, profile: StructuredProfile) -> bool:
    first = span.text.strip().split("\n", 1)[0].strip()
    return any(pattern.search(first) for pattern in profile.filler_lines)


def parameter_columns(header: list[str], profile: StructuredProfile) -> dict[str, int | str | None] | None:
    """The column roles of a parameter table header, or ``None`` when it is not one."""
    if not header:
        return None
    match = _SECTION_PREFIX.match(header[0])
    ini, first = (match.group(1).strip(), match.group(2)) if match else (None, header[0])
    if fold(first) not in profile.parameter_name_headers:
        return None
    roles: dict[str, int | str | None] = {"ini": ini, "default": None, "description": None, "allowed": None}
    for index, cell in enumerate(header[1:], start=1):
        folded = fold(cell)
        for role, names in (
            ("default", profile.default_headers),
            ("description", profile.description_headers),
            ("allowed", profile.allowed_headers),
        ):
            if folded in names and roles[role] is None:
                roles[role] = index
    return roles if roles["default"] is not None else None


def _split_components(folded: str, components: tuple[Component, ...]) -> list[Component] | None:
    """``folded`` as one component, or as a concatenation of up to three, else ``None``."""
    for component in components:
        if folded == component.folded:
            return [component]
    for first in components:
        if folded.startswith(first.folded):
            rest = folded[len(first.folded) :]
            for second in components:
                if rest == second.folded:
                    return [first, second]
                if rest.startswith(second.folded):
                    for third in components:
                        if rest[len(second.folded) :] == third.folded:
                            return [first, second, third]
    return None


def compatibility_columns(header: list[str], profile: StructuredProfile) -> dict[int, list[Component] | None] | None:
    if len(header) < 3 or not fold(header[0]) or _split_components(fold(header[0]), profile.components):
        return None
    columns = {index: _split_components(fold(cell), profile.components) for index, cell in enumerate(header) if index}
    return columns if sum(1 for found in columns.values() if found) >= 2 else None


def _recognized(header: list[str], profile: StructuredProfile) -> bool:
    return parameter_columns(header, profile) is not None or compatibility_columns(header, profile) is not None


def logical_tables(spans: list[SpanInput], outline: Outline, profile: StructuredProfile) -> list[LogicalTable]:
    tables: list[LogicalTable] = []
    open_table: LogicalTable | None = None
    for span in spans:
        if span.kind != "table":
            if not _is_filler(span, profile):
                open_table = None
            continue
        # Caption lines Docling puts into the table span carry no cell separator.
        lines = [cells(line) for line in span.text.split("\n") if "|" in line]
        if not lines:
            continue
        section = outline.span_section.get(span.ordinal)
        if _recognized(lines[0], profile):
            open_table = LogicalTable(lines[0], section)
            tables.append(open_table)
            lines = lines[1:]
        elif open_table is None or open_table.section != section:
            open_table = None
            continue
        open_table.rows.extend((row, span.ordinal) for row in lines)
    return tables


def _scope(outline: Outline, section: str | None, ini: str | None) -> tuple[str, str]:
    if ini:
        return "ini", ini
    for item in outline.chain(section):
        if item.plugin:
            return "plugin", item.plugin
        if item.number and is_identifier(item.title):
            return "plugin", item.title
    return "none", ""


def _cell(row: list[str], index: int | str | None) -> str:
    return row[index] if isinstance(index, int) and index < len(row) else ""


def add_parameters(extraction: Extraction, outline: Outline, table: LogicalTable, profile: StructuredProfile) -> None:
    roles = parameter_columns(table.header, profile)
    kind, scope = _scope(outline, table.section, roles["ini"])
    section = section_ref(outline, table.section)
    current: NodeRef | None = None
    for row, ordinal in table.rows:
        name = re.sub(r"^(\w+)- (\w+)$", r"\1\2", row[0]) if row else ""
        description = dehyphenate(_cell(row, roles["description"]))
        if not name:
            if current is not None and description:
                props = extraction.nodes[current].properties
                props["description"] = clip(f"{props['description']} {description}".strip())
            continue
        if not _NAME.fullmatch(name) or fold(name) in profile.parameter_name_headers:
            current = None
            continue
        default = _cell(row, roles["default"])
        allowed = _cell(row, roles["allowed"])
        if not allowed:
            for pattern in profile.allowed_value_patterns:
                found = pattern.search(description)
                if found:
                    allowed = found.group(1)
                    break
        unit_word = _UNIT.search(description)
        key = f"{outline.document_key}|{kind}:{scope}|{name}"
        if NodeRef("Parameter", key) in extraction.nodes:
            extraction.warn("parameter_repeated")
            current = None
            continue
        label = f"[{scope}] {name}" if kind == "ini" else f"{scope}.{name}" if kind == "plugin" else name
        current = extraction.node(
            "Parameter", key, label, SpanRef(ordinal), name=name, scope_kind=kind, scope=scope or None,
            default=None if default in ("", MANDATORY) else default, mandatory=default == MANDATORY,
            allowed_values=clip(allowed, 200) or None, description=clip(description),
            unit=dict(profile.units).get(unit_word.group(1).lower()) if unit_word else None,
        )
        extraction.edge("documented_in", current, section, SpanRef(ordinal))


def _strip_component(value: str, component: Component) -> str:
    words = value.split()
    for index in range(1, len(words) + 1):
        if fold(" ".join(words[:index])) == component.folded:
            return " ".join(words[index:])
    return value


def add_compatibility(extraction: Extraction, outline: Outline, table: LogicalTable, profile: StructuredProfile):
    columns = compatibility_columns(table.header, profile)
    product = dehyphenate(table.header[0])
    section = section_ref(outline, table.section)
    for row_index, (row, ordinal) in enumerate(table.rows):
        version = row[0].strip() if row else ""
        if not _VERSION.fullmatch(version):
            continue
        cite = SpanRef(ordinal)
        release = extraction.node(
            "Version", f"product:{fold(product)}@{version}", f"{product} {version}", cite,
            product=product, version=version,
        )
        extraction.edge("documented_in", release, section, cite)
        ambiguous = False
        for index, components in columns.items():
            value = dehyphenate(_cell(row, index))
            if value.casefold() in _EMPTY_VALUES:
                continue
            if components is None:
                ambiguous = True
                continue
            if len(components) == 1:
                pairs = [(components[0], _strip_component(value, components[0]))]
            else:
                tokens = value.split()
                if len(tokens) != len(components):
                    ambiguous = True
                    continue
                pairs = list(zip(components, tokens, strict=True))
            for component, versions in pairs:
                if versions.casefold() in _EMPTY_VALUES:
                    continue
                target = extraction.node(
                    "Component", f"component:{component.folded}", component.name, cite, name=component.name
                )
                extraction.edge(
                    component.relation, release, target, cite, versions=versions, product=product, release=version
                )
        if ambiguous:
            extraction.warn("table_header_ambiguous")
            row_ref = extraction.node(
                "TableRow", f"{outline.document_key}#row{ordinal}.{row_index}", clip(" | ".join(row), 200),
                cite, header=[clip(cell, 60) for cell in table.header], cells=[clip(cell, 80) for cell in row],
            )
            extraction.edge("documented_in", row_ref, section, cite)
            extraction.edge("row_of", release, row_ref, cite)


def add_tables(extraction: Extraction, spans: list[SpanInput], outline: Outline, profile: StructuredProfile) -> None:
    for table in logical_tables(spans, outline, profile):
        if parameter_columns(table.header, profile) is not None:
            add_parameters(extraction, outline, table, profile)
        else:
            add_compatibility(extraction, outline, table, profile)


__all__ = [
    "LogicalTable",
    "add_compatibility",
    "add_parameters",
    "add_tables",
    "cells",
    "compatibility_columns",
    "dehyphenate",
    "logical_tables",
    "parameter_columns",
]
