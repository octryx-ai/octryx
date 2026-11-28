"""``{{placeholder}}`` template fill for Word, PowerPoint and Excel that keeps the template's styling."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")
_MISSING = object()

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def lookup(data: dict[str, Any], key: str) -> Any:
    value: Any = data
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
    return value


def render_value(value: Any, *, list_separator: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return list_separator.join(render_value(item, list_separator=list_separator) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


class FillReport:
    def __init__(self) -> None:
        self.replaced = 0
        self.missing: set[str] = set()

    def as_dict(self) -> dict[str, Any]:
        return {"replaced": self.replaced, "missing": sorted(self.missing)}


def _fill_text_nodes(nodes: list[Any], data: dict[str, Any], report: FillReport, *, list_separator: str) -> None:
    texts = [node.text or "" for node in nodes]
    full = "".join(texts)
    if "{{" not in full:
        return
    matches = [match for match in PLACEHOLDER.finditer(full)]
    for match in reversed(matches):
        value = lookup(data, match.group(1))
        if value is _MISSING:
            report.missing.add(match.group(1))
            continue
        replacement = render_value(value, list_separator=list_separator)
        start, end = match.span()
        offset = 0
        first = True
        for position, text in enumerate(texts):
            node_start, node_end = offset, offset + len(text)
            offset = node_end
            if node_end <= start or node_start >= end:
                continue
            before = text[: max(0, start - node_start)] if node_start <= start else ""
            after = text[end - node_start :] if node_end > end else ""
            texts[position] = (before + replacement + after) if first else after
            first = False
        report.replaced += 1
    for node, text in zip(nodes, texts, strict=True):
        if node.text != text:
            node.text = text
            if text != text.strip():
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _fill_paragraph_elements(
    paragraphs: Iterable[Any], text_tag: str, data: dict[str, Any], report: FillReport, *, list_separator: str
) -> None:
    for paragraph in paragraphs:
        nodes = [node for node in paragraph.iter(text_tag)]
        if nodes:
            _fill_text_nodes(nodes, data, report, list_separator=list_separator)


def fill_word(document: Any, data: dict[str, Any]) -> dict[str, Any]:
    report = FillReport()
    roots = [document.element.body]
    for rel in document.part.rels.values():
        if rel.is_external:
            continue
        if rel.reltype.rsplit("/", 1)[-1] in {"header", "footer", "footnotes", "endnotes"}:
            element = getattr(rel.target_part, "element", None)
            if element is not None:
                roots.append(element)
    for root in roots:
        _fill_paragraph_elements(root.iter(f"{{{_W_NS}}}p"), f"{{{_W_NS}}}t", data, report, list_separator=", ")
    return report.as_dict()


def fill_slides(presentation: Any, data: dict[str, Any]) -> dict[str, Any]:
    report = FillReport()
    for slide in presentation.slides:
        roots = [slide.shapes._spTree]
        if slide.has_notes_slide:
            roots.append(slide.notes_slide.shapes._spTree)
        for root in roots:
            _fill_paragraph_elements(root.iter(f"{{{_A_NS}}}p"), f"{{{_A_NS}}}t", data, report, list_separator=", ")
    return report.as_dict()


def fill_sheets(workbook: Any, data: dict[str, Any]) -> dict[str, Any]:
    from .sheets import set_literal

    report = FillReport()
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                if not isinstance(cell.value, str) or "{{" not in cell.value:
                    continue
                whole = PLACEHOLDER.fullmatch(cell.value.strip())
                if whole:
                    value = lookup(data, whole.group(1))
                    if value is _MISSING:
                        report.missing.add(whole.group(1))
                        continue
                    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
                    set_literal(cell, value if is_number else render_value(value, list_separator=", "))
                    report.replaced += 1
                    continue
                set_literal(cell, _fill_string(cell.value, data, report))
    return report.as_dict()


def _fill_string(text: str, data: dict[str, Any], report: FillReport) -> str:
    def _replace(match: re.Match[str]) -> str:
        value = lookup(data, match.group(1))
        if value is _MISSING:
            report.missing.add(match.group(1))
            return match.group(0)
        report.replaced += 1
        return render_value(value, list_separator=", ")

    return PLACEHOLDER.sub(_replace, text)


def fill_document(kind: str, document: Any, data: dict[str, Any]) -> dict[str, Any]:
    if kind == "docx":
        return fill_word(document, data)
    if kind == "pptx":
        return fill_slides(document, data)
    return fill_sheets(document, data)


def unresolved_placeholders(text: str) -> list[str]:
    return sorted({match.group(1) for match in PLACEHOLDER.finditer(text or "")})


__all__ = [
    "PLACEHOLDER",
    "fill_document",
    "fill_sheets",
    "fill_slides",
    "fill_word",
    "lookup",
    "render_value",
    "unresolved_placeholders",
]
