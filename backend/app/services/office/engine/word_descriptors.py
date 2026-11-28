"""Word documents (python-docx): descriptors of paragraphs, runs, tables and content controls."""

from __future__ import annotations

from typing import Any

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def heading_level(paragraph: Paragraph) -> int | None:
    style_name = str(getattr(paragraph.style, "name", "") or "")
    if style_name == "Title":
        return 0
    if style_name.lower().startswith("heading "):
        level = style_name.split(" ", 1)[1]
        return int(level) if level.isdigit() else None
    return None


def paragraph_kind(paragraph: Paragraph) -> str:
    if heading_level(paragraph) is not None:
        return "heading"
    style_name = str(getattr(paragraph.style, "name", "") or "").lower()
    if style_name.startswith("list") or paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None:
        return "list_item"
    return "paragraph"


def run_descriptor(run: Any, path: str) -> dict[str, Any]:
    font = run.font
    return {
        "type": "run",
        "path": path,
        "text": run.text,
        "bold": font.bold,
        "italic": font.italic,
        "underline": bool(font.underline) if font.underline is not None else None,
        "size": font.size.pt if font.size else None,
        "font": font.name,
        "color": str(font.color.rgb) if font.color is not None and font.color.type is not None else None,
    }


def paragraph_descriptor(paragraph: Paragraph, path: str) -> dict[str, Any]:
    style = paragraph.style
    descriptor = {
        "type": "paragraph",
        "kind": paragraph_kind(paragraph),
        "path": path,
        "text": paragraph.text,
        "style": getattr(style, "name", None),
        "style_id": getattr(style, "style_id", None),
        "alignment": _alignment_name(paragraph.alignment),
        "runs": len(paragraph.runs),
        "pictures": len(paragraph._p.xpath(".//pic:pic")),
        "charts": len(paragraph._p.xpath(".//c:chart")),
    }
    level = heading_level(paragraph)
    if level is not None:
        descriptor["level"] = level
    return descriptor


def _alignment_name(value: Any) -> str | None:
    if value is None:
        return None
    return {WD_ALIGN_PARAGRAPH.CENTER: "center", WD_ALIGN_PARAGRAPH.RIGHT: "right"}.get(
        value, "justify" if value == WD_ALIGN_PARAGRAPH.JUSTIFY else "left"
    )


def table_text(table: Table) -> str:
    return "\n".join(" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows)


def body_blocks(document: Any) -> list[tuple[str, str, Any]]:
    blocks: list[tuple[str, str, Any]] = []
    counts = {"p": 0, "tbl": 0}
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            counts["p"] += 1
            blocks.append(("paragraph", f"/body/p[{counts['p']}]", Paragraph(child, document)))
        elif child.tag == qn("w:tbl"):
            counts["tbl"] += 1
            blocks.append(("table", f"/body/tbl[{counts['tbl']}]", Table(child, document)))
    return blocks


def content_control_descriptor(sdt: Any, path: str) -> dict[str, Any]:
    properties = sdt.find(qn("w:sdtPr"))
    name = ""
    control_type = "rich_text"
    if properties is not None:
        for tag in ("w:alias", "w:tag"):
            element = properties.find(qn(tag))
            if element is not None and element.get(qn("w:val")):
                name = element.get(qn("w:val"))
                break
        for tag, label in (("w:text", "text"), ("w:date", "date"), ("w:dropDownList", "drop_down"),
                           ("w:comboBox", "combo_box"), ("w:picture", "picture")):
            if properties.find(qn(tag)) is not None:
                control_type = label
        if properties.find("{http://schemas.microsoft.com/office/word/2010/wordml}checkbox") is not None:
            control_type = "checkbox"
    text = "".join(node.text or "" for node in sdt.iter(qn("w:t")))
    return {"type": "content_control", "path": path, "name": name, "control_type": control_type, "text": text}


__all__ = [
    "body_blocks",
    "content_control_descriptor",
    "heading_level",
    "paragraph_descriptor",
    "paragraph_kind",
    "run_descriptor",
    "table_text",
]
