"""Word block builders: the element types ``add`` creates (paragraphs, headings, tables, TOC, equations, …)."""

from __future__ import annotations

import re
from typing import Any

from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.shared import Pt

from .paths import INVALID_REQUEST, OfficeEngineError, flag, length_emu
from .word_props import (
    apply_paragraph_props,
    apply_run_props,
    chart_into,
    find_style,
    page_break,
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_HEADING_SIZES = {0: 26, 1: 16, 2: 13, 3: 12}


def style_or_none(document: Any, name: str) -> Any:
    try:
        return find_style(document, name)
    except OfficeEngineError:
        return None


def add_paragraph(document: Any, container: Any, text: str = "", **props: Any) -> Any:
    paragraph = container.add_paragraph()
    apply_paragraph_props(document, paragraph, {"text": text, **props})
    return paragraph


def add_heading(document: Any, container: Any, text: str, level: int = 1, **props: Any) -> Any:
    level = max(0, min(int(level), 9))
    style = style_or_none(document, "Title" if level == 0 else f"Heading {level}")
    paragraph = container.add_paragraph()
    if style is not None:
        paragraph.style = style
        apply_paragraph_props(document, paragraph, {"text": text, **props})
        return paragraph
    apply_paragraph_props(document, paragraph, {"text": text, **props})
    for run in paragraph.runs:
        run.font.bold = True
        run.font.size = Pt(_HEADING_SIZES.get(level, 11))
    paragraph._p.get_or_add_pPr().append(parse_xml(f'<w:outlineLvl xmlns:w="{_W}" w:val="{max(level - 1, 0)}"/>'))
    return paragraph


def add_list_item(document: Any, container: Any, text: str, *, numbered: bool = False, number: int = 1) -> Any:
    style = style_or_none(document, "List Number" if numbered else "List Bullet")
    if style is not None:
        paragraph = container.add_paragraph()
        paragraph.style = style
        paragraph.add_run(text)
        return paragraph
    return add_paragraph(document, container, f"{number}. {text}" if numbered else f"• {text}")


def add_table(document: Any, container: Any, *, headers: list[Any] | None = None, rows: list[list[Any]] | None = None,
              row_count: int = 0, col_count: int = 0, style: str = "") -> Any:
    headers = [str(item) for item in headers or []]
    body = [[("" if value is None else str(value)) for value in row] for row in rows or []]
    cols = max(col_count, len(headers), max((len(row) for row in body), default=0))
    total_rows = max(row_count, len(body) + (1 if headers else 0))
    if cols < 1 or total_rows < 1:
        raise OfficeEngineError(INVALID_REQUEST, "a table needs at least one row and one column")
    table = container.add_table(rows=total_rows, cols=cols)
    chosen = style_or_none(document, style) if style else style_or_none(document, "Table Grid")
    if chosen is not None:
        table.style = chosen
    offset = 0
    if headers:
        for column, value in enumerate(headers):
            cell_paragraph = table.rows[0].cells[column].paragraphs[0]
            apply_run_props(cell_paragraph.add_run(value), {"bold": True})
        offset = 1
    for r, row in enumerate(body):
        for column, value in enumerate(row[:cols]):
            table.rows[r + offset].cells[column].paragraphs[0].add_run(value)
    return table


def add_picture(container_paragraph: Any, path: str, *, width: Any = None, height: Any = None, alt: str = "") -> Any:
    run = container_paragraph.add_run()
    shape = run.add_picture(
        str(path),
        width=length_emu(width, default_unit="in") if width else None,
        height=length_emu(height, default_unit="in") if height else None,
    )
    if alt:
        shape._inline.docPr.set("descr", alt)
    return shape


TOC_LEVELS = re.compile(r"^[1-9]-[1-9]$")


def add_toc(document: Any, container: Any, *, title: str = "", levels: str = "1-3") -> Any:
    if not TOC_LEVELS.fullmatch(str(levels)) or int(levels[0]) > int(levels[2]):
        raise OfficeEngineError(INVALID_REQUEST, "TOC levels look like 1-3")
    if title:
        heading_style = style_or_none(document, "TOC Heading")
        if heading_style is not None:
            title_paragraph = container.add_paragraph(title)
            title_paragraph.style = heading_style
        else:
            add_heading(document, container, title, 1)
    paragraph = container.add_paragraph()
    run = paragraph.add_run()._r
    run.append(parse_xml(f'<w:fldChar xmlns:w="{_W}" w:fldCharType="begin" w:dirty="true"/>'))
    instruction = parse_xml(f'<w:instrText xmlns:w="{_W}" xml:space="preserve"> TOC \\o "{levels}" \\h \\z \\u </w:instrText>')
    run.append(instruction)
    run.append(parse_xml(f'<w:fldChar xmlns:w="{_W}" w:fldCharType="separate"/>'))
    run.append(parse_xml(f'<w:t xmlns:w="{_W}">Update the table of contents to fill it.</w:t>'))
    run.append(parse_xml(f'<w:fldChar xmlns:w="{_W}" w:fldCharType="end"/>'))
    settings = document.settings.element
    if settings.find(qn("w:updateFields")) is None:
        settings.append(parse_xml(f'<w:updateFields xmlns:w="{_W}" w:val="true"/>'))
    return paragraph


def add_equation(container: Any, formula: str) -> Any:
    paragraph = container.add_paragraph()
    text = formula.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    paragraph._p.append(
        parse_xml(f'<m:oMathPara xmlns:m="{_M}"><m:oMath><m:r><m:t>{text}</m:t></m:r></m:oMath></m:oMathPara>')
    )
    return paragraph


def add_block(document: Any, container: Any, kind: str, props: dict[str, Any]) -> Any:
    text = str(props.get("text") or "")
    rest = {key: value for key, value in props.items() if key not in {"text", "level", "numbered"}}
    if kind == "paragraph":
        return add_paragraph(document, container, text, **rest)._p
    if kind == "heading":
        return add_heading(document, container, text, int(props.get("level") or 1), **rest)._p
    if kind == "list_item":
        return add_list_item(document, container, text, numbered=flag(props.get("numbered", False)))._p
    if kind == "table":
        data = props.get("data") if isinstance(props.get("data"), list) else props.get("rows")
        table = add_table(
            document,
            container,
            headers=props.get("headers") if isinstance(props.get("headers"), list) else None,
            rows=[row for row in data if isinstance(row, list)] if isinstance(data, list) else None,
            row_count=int(props.get("rows") or 0) if not isinstance(props.get("rows"), list) else 0,
            col_count=int(props.get("cols") or 0),
            style=str(props.get("style") or ""),
        )
        return table._tbl
    if kind == "picture":
        paragraph = container.add_paragraph()
        add_picture(paragraph, str(props.get("path") or ""), width=props.get("width"), height=props.get("height"),
                    alt=str(props.get("alt") or ""))
        return paragraph._p
    if kind == "page_break":
        paragraph = container.add_paragraph()
        page_break(paragraph)
        return paragraph._p
    if kind == "toc":
        return add_toc(document, container, title=str(props.get("title") or ""), levels=str(props.get("levels") or "1-3"))._p
    if kind == "equation":
        return add_equation(container, str(props.get("formula") or text))._p
    paragraph = container.add_paragraph()
    chart_into(document, paragraph, props)
    return paragraph._p


__all__ = [
    "add_block",
    "add_equation",
    "add_heading",
    "add_list_item",
    "add_paragraph",
    "add_picture",
    "add_table",
    "add_toc",
    "style_or_none",
]
