"""Word document views: ``text``, ``outline``, ``annotated``, ``stats``, ``forms``."""

from __future__ import annotations

from collections import Counter
from typing import Any

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .paths import text_window
from .word_descriptors import body_blocks, content_control_descriptor, heading_level, paragraph_kind, table_text


def _elements(document: Any) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for kind, path, block in body_blocks(document):
        if kind == "table":
            elements.append({"type": "table", "path": path, "text": table_text(block)})
            continue
        style = getattr(block.style, "name", None)
        elements.append({"type": paragraph_kind(block), "path": path, "text": block.text, "style": style})
    return elements


def text_view(document: Any, *, start: int | None = None, end: int | None = None, max_lines: int | None = None) -> dict[str, Any]:
    elements = _elements(document)
    return {"totalElements": len(elements), "elements": text_window(elements, start=start, end=end, max_lines=max_lines)}


def outline_view(document: Any) -> dict[str, Any]:
    headings: list[dict[str, Any]] = []
    blocks = body_blocks(document)
    for line, (kind, path, block) in enumerate(blocks, start=1):
        if kind != "paragraph":
            continue
        level = heading_level(block)
        if level is None or not block.text.strip():
            continue
        headings.append({"level": max(level, 1), "line": line, "path": path, "style": block.style.name, "text": block.text})
    body = document.element.body
    return {
        "headings": headings,
        "paragraphs": sum(1 for kind, _, _ in blocks if kind == "paragraph"),
        "tables": sum(1 for kind, _, _ in blocks if kind == "table"),
        "images": len(body.xpath(".//pic:pic")),
        "charts": len(body.xpath(".//c:chart")),
    }


def annotated_view(document: Any, *, start: int | None = None, end: int | None = None, max_lines: int | None = None) -> dict[str, Any]:
    lines: list[str] = []
    for kind, path, block in body_blocks(document):
        if kind == "table":
            lines.append(f"[{path}] table {len(block.rows)}x{len(block.columns)}")
            lines.extend(f"    {row}" for row in table_text(block).splitlines())
            continue
        marks = []
        if any(run.bold for run in block.runs if run.text.strip()):
            marks.append("bold")
        if block._p.xpath(".//pic:pic"):
            marks.append("picture")
        if block._p.xpath(".//c:chart"):
            marks.append("chart")
        annotation = ", ".join([str(block.style.name), *marks])
        lines.append(f"[{path}] ({annotation}) {block.text}")
    window = text_window(lines, start=start, end=end, max_lines=max_lines)
    return {"Content": "\n".join(window), "totalLines": len(lines)}


def stats_view(document: Any) -> dict[str, Any]:
    styles: Counter[str] = Counter()
    fonts: Counter[str] = Counter()
    characters = 0
    words = 0
    paragraphs = 0
    headings = 0
    body = document.element.body
    for paragraph_element in body.iter(qn("w:p")):
        paragraph = Paragraph(paragraph_element, document)
        text = paragraph.text
        paragraphs += 1
        characters += len(text)
        words += len(text.split())
        if text.strip():
            styles[str(paragraph.style.name)] += 1
            if heading_level(paragraph) is not None:
                headings += 1
        for run in paragraph.runs:
            if run.text.strip():
                fonts[str(run.font.name or "(theme)")] += 1
    return {
        "paragraphs": paragraphs,
        "headings": headings,
        "words": words,
        "totalCharacters": characters,
        "tables": len(body.xpath(".//w:tbl")),
        "images": len(body.xpath(".//pic:pic")),
        "charts": len(body.xpath(".//c:chart")),
        "sections": len(document.sections),
        "styleDistribution": dict(styles.most_common()),
        "fontUsage": dict(fonts.most_common()),
    }


def forms_view(document: Any) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    body = document.element.body
    for index, sdt in enumerate(body.iter(qn("w:sdt")), start=1):
        descriptor = content_control_descriptor(sdt, f"/body/sdt[{index}]")
        fields.append(
            {
                "name": descriptor["name"] or f"Control {index}",
                "type": descriptor["control_type"],
                "path": descriptor["path"],
                "value": descriptor["text"],
                "required": False,
            }
        )
    for index, form_data in enumerate(body.iter(qn("w:ffData")), start=1):
        name_element = form_data.find(qn("w:name"))
        field_type = "text"
        if form_data.find(qn("w:checkBox")) is not None:
            field_type = "checkbox"
        elif form_data.find(qn("w:ddList")) is not None:
            field_type = "drop_down"
        fields.append(
            {
                "name": name_element.get(qn("w:val")) if name_element is not None else f"Field {index}",
                "type": field_type,
                "path": f"/body/formfield[{index}]",
                "required": False,
            }
        )
    protection = document.settings.element.find(qn("w:documentProtection"))
    edit = protection.get(qn("w:edit")) if protection is not None else None
    enforced = protection is not None and str(protection.get(qn("w:enforcement")) or "").lower() in {"1", "true", "on"}
    return {"protection": edit or "none", "protectionEnforced": enforced, "fields": fields}


__all__ = ["annotated_view", "forms_view", "outline_view", "stats_view", "text_view"]
