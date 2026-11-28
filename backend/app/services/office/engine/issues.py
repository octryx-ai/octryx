"""Static document checks: the ``issues`` view and the core of ``validate``."""

from __future__ import annotations

import re
from typing import Any

from .fill import unresolved_placeholders

_SHEET_REF = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_][\w.]*))!")


def _issue(code: str, severity: str, message: str, path: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "path": path}


def word_issues(document: Any) -> list[dict[str, Any]]:
    from docx.oxml.ns import qn

    from .word_descriptors import body_blocks, heading_level, table_text

    issues: list[dict[str, Any]] = []
    blocks = body_blocks(document)
    if not any((block.text if kind == "paragraph" else table_text(block)).strip() for kind, _, block in blocks):
        issues.append(_issue("empty_document", "warning", "The document has no text.", "/body"))
    previous_level = 0
    for kind, path, block in blocks:
        text = block.text if kind == "paragraph" else table_text(block)
        for key in unresolved_placeholders(text):
            issues.append(_issue("unresolved_placeholder", "warning", f"Placeholder {{{{{key}}}}} has no value.", path))
        if kind != "paragraph":
            continue
        level = heading_level(block)
        if level is None or level == 0:
            continue
        if not text.strip():
            issues.append(_issue("empty_heading", "warning", "A heading paragraph has no text.", path))
        elif previous_level and level > previous_level + 1:
            issues.append(_issue("heading_level_skip", "info", f"Heading level jumps from {previous_level} to {level}.", path))
        previous_level = level
    for index, doc_pr in enumerate(document.element.body.iter(qn("wp:docPr")), start=1):
        if doc_pr.getparent().find(qn("a:graphic")) is not None and not str(doc_pr.get("descr") or "").strip():
            issues.append(_issue("image_missing_alt_text", "info", f"Drawing {doc_pr.get('name') or index} has no alt text.", f"/body/drawing[{index}]"))
    return issues


def slide_issues(presentation: Any) -> list[dict[str, Any]]:
    from .slides import shape_paths, shape_type

    issues: list[dict[str, Any]] = []
    width, height = presentation.slide_width, presentation.slide_height
    if len(presentation.slides) == 0:
        issues.append(_issue("empty_presentation", "warning", "The presentation has no slides.", "/"))
    for index, slide in enumerate(presentation.slides, start=1):
        slide_path = f"/slide[{index}]"
        has_content = False
        for path, shape in shape_paths(slide, slide_path):
            kind = shape_type(shape)
            text = shape.text_frame.text if getattr(shape, "has_text_frame", False) and shape.has_text_frame else ""
            if kind == "table":
                text = "\n".join(cell.text for row in shape.table.rows for cell in row.cells)
            has_content = has_content or bool(text.strip()) or kind in {"picture", "chart", "table", "group", "frame"}
            for key in unresolved_placeholders(text):
                issues.append(_issue("unresolved_placeholder", "warning", f"Placeholder {{{{{key}}}}} has no value.", path))
            if shape.left is not None and shape.width is not None and (
                shape.left < 0 or shape.top < 0 or shape.left + shape.width > width or shape.top + shape.height > height
            ):
                issues.append(_issue("shape_off_slide", "warning", f"{shape.name} extends beyond the slide.", path))
            if kind == "picture" and not shape._element.xpath("./p:nvPicPr/p:cNvPr/@descr"):
                issues.append(_issue("image_missing_alt_text", "info", f"Picture {shape.name} has no alt text.", path))
            if shape.is_placeholder and kind == "shape" and not text.strip():
                issues.append(_issue("empty_placeholder", "info", f"Placeholder {shape.name} is empty.", path))
        if not has_content:
            issues.append(_issue("empty_slide", "warning", "The slide has no text, picture, table or chart.", slide_path))
    return issues


def sheet_issues(workbook: Any) -> list[dict[str, Any]]:
    from .sheets import ERROR_VALUES

    issues: list[dict[str, Any]] = []
    names = set(workbook.sheetnames)
    if not any(cell.value is not None for worksheet in workbook.worksheets for row in worksheet.iter_rows() for cell in row):
        issues.append(_issue("empty_workbook", "info", "The workbook has no values.", "/"))
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                value = cell.value
                if not isinstance(value, str):
                    continue
                path = f"/{worksheet.title}/{cell.coordinate}"
                if value.strip() in ERROR_VALUES:
                    issues.append(_issue("formula_error_value", "error", f"{cell.coordinate} holds {value.strip()}.", path))
                if value.startswith("="):
                    if "#REF!" in value:
                        issues.append(_issue("broken_reference", "error", f"{cell.coordinate} refers to a deleted range.", path))
                    for match in _SHEET_REF.finditer(value):
                        referenced = (match.group(1) or match.group(2) or "").replace("''", "'")
                        if referenced and referenced not in names:
                            issues.append(_issue("unknown_sheet_reference", "error", f"{cell.coordinate} refers to missing sheet {referenced!r}.", path))
                for key in unresolved_placeholders(value):
                    issues.append(_issue("unresolved_placeholder", "warning", f"Placeholder {{{{{key}}}}} has no value.", path))
    return issues


def document_issues(kind: str, document: Any) -> list[dict[str, Any]]:
    if kind == "docx":
        return word_issues(document)
    if kind == "pptx":
        return slide_issues(document)
    return sheet_issues(document)


def issues_view(kind: str, document: Any, *, issue_type: str = "", limit: int | None = None) -> dict[str, Any]:
    found = document_issues(kind, document)
    wanted = str(issue_type or "").strip().lower()
    if wanted:
        found = [item for item in found if wanted in {item["code"], item["severity"]}]
    total = len(found)
    if limit:
        found = found[: max(0, int(limit))]
    return {"count": total, "issues": found}


__all__ = ["document_issues", "issues_view", "sheet_issues", "slide_issues", "word_issues"]
