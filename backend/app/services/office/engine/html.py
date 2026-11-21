"""In-process HTML preview of Word, PowerPoint and Excel files.

A structural preview: Word headings/paragraphs/lists/tables with inline pictures, Excel sheets as tables (the
first rows and columns), PowerPoint slides with their shapes placed by geometry. Everything is escaped and the
page carries no script. A pixel-faithful rendering is LibreOffice's job (``services/office/render.py``).
"""

from __future__ import annotations

import base64
from html import escape
from typing import Any

MAX_SHEET_ROWS = 200
MAX_SHEET_COLS = 40
MAX_PICTURE_BYTES = 2 * 1024 * 1024

_STYLE = """
body{font-family:Calibri,Arial,sans-serif;margin:0;padding:24px;background:#f4f5f7;color:#1f2933}
.page{background:#fff;max-width:860px;margin:0 auto 24px;padding:40px 56px;box-shadow:0 1px 3px rgba(0,0,0,.12)}
table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #cbd2d9;padding:4px 8px;font-size:13px;vertical-align:top}
th{background:#eef1f4}.sheet h2{font-size:15px}.chart{display:inline-block;border:1px dashed #9aa5b1;padding:8px 12px;color:#52606d;font-size:13px}
.slide{position:relative;background:#fff;margin:0 auto 24px;box-shadow:0 1px 3px rgba(0,0,0,.18);overflow:hidden}
.shape{position:absolute;overflow:hidden;font-size:12px;line-height:1.25;white-space:pre-wrap}
.slide-label{max-width:960px;margin:0 auto 4px;font-size:12px;color:#52606d}
img{max-width:100%}
"""


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head><body>{body}</body></html>"
    )


def _image_data(part: Any) -> str:
    blob = getattr(part, "blob", b"") or b""
    if len(blob) > MAX_PICTURE_BYTES:
        return ""
    content_type = getattr(part, "content_type", "image/png")
    if not content_type.startswith("image/") or content_type == "image/svg+xml":
        return ""
    return f"data:{content_type};base64,{base64.b64encode(blob).decode('ascii')}"


def _runs_html(paragraph: Any) -> str:
    parts: list[str] = []
    for run in paragraph.runs:
        text = escape(run.text)
        if run.bold:
            text = f"<b>{text}</b>"
        if run.italic:
            text = f"<i>{text}</i>"
        parts.append(text)
    return "".join(parts)


def word_html(document: Any, title: str) -> str:
    from .word_descriptors import body_blocks, heading_level, paragraph_kind

    chunks: list[str] = []
    in_list = False
    for kind, _, block in body_blocks(document):
        is_list = kind == "paragraph" and paragraph_kind(block) == "list_item"
        if in_list and not is_list:
            chunks.append("</ul>")
        if is_list and not in_list:
            chunks.append("<ul>")
        in_list = is_list
        if kind == "table":
            rows = "".join(
                "<tr>" + "".join(f"<td>{escape(cell.text)}</td>" for cell in row.cells) + "</tr>" for row in block.rows
            )
            chunks.append(f"<table>{rows}</table>")
            continue
        for blip in block._p.xpath(".//a:blip/@r:embed"):
            source = _image_data(document.part.related_parts.get(blip))
            if source:
                chunks.append(f'<p><img src="{source}" alt=""></p>')
        if block._p.xpath(".//c:chart"):
            chunks.append('<p><span class="chart">Chart</span></p>')
        content = _runs_html(block)
        if not content.strip():
            continue
        level = heading_level(block)
        if is_list:
            chunks.append(f"<li>{content}</li>")
        elif level is not None:
            tag = f"h{min(max(level, 1), 6)}"
            chunks.append(f"<{tag}>{content}</{tag}>")
        else:
            chunks.append(f"<p>{content}</p>")
    if in_list:
        chunks.append("</ul>")
    return _page(title, f'<div class="page">{"".join(chunks)}</div>')


def sheets_html(workbook: Any, title: str) -> str:
    from openpyxl.utils import get_column_letter

    from .sheets_describe import chart_title

    chunks: list[str] = []
    for worksheet in workbook.worksheets:
        max_col = min(worksheet.max_column, MAX_SHEET_COLS)
        header = "<tr><th></th>" + "".join(f"<th>{get_column_letter(col)}</th>" for col in range(1, max_col + 1)) + "</tr>"
        rows = []
        for row in worksheet.iter_rows(min_row=1, max_row=min(worksheet.max_row, MAX_SHEET_ROWS), max_col=max_col):
            cells = "".join(f"<td>{escape('' if cell.value is None else str(cell.value))}</td>" for cell in row)
            rows.append(f"<tr><th>{row[0].row}</th>{cells}</tr>")
        charts = "".join(f'<span class="chart">Chart: {escape(chart_title(chart) or type(chart).__name__)}</span> ' for chart in worksheet._charts)
        chunks.append(f'<div class="page sheet"><h2>{escape(worksheet.title)}</h2>{charts}<table>{header}{"".join(rows)}</table></div>')
    return _page(title, "".join(chunks))


def _shape_html(shape: Any, width: int, height: int) -> str:
    from .slides import shape_type

    if shape.left is None or shape.width is None:
        return ""
    box = (
        f"left:{shape.left / width * 100:.2f}%;top:{shape.top / height * 100:.2f}%;"
        f"width:{shape.width / width * 100:.2f}%;height:{shape.height / height * 100:.2f}%"
    )
    kind = shape_type(shape)
    if kind == "picture":
        try:
            source = _image_data(shape.image)
        except (KeyError, ValueError, AttributeError):  # linked or missing image part
            source = ""
        return f'<img class="shape" style="{box};object-fit:contain" src="{source}" alt="">' if source else ""
    if kind == "table":
        rows = "".join("<tr>" + "".join(f"<td>{escape(cell.text)}</td>" for cell in row.cells) + "</tr>" for row in shape.table.rows)
        return f'<div class="shape" style="{box}"><table style="width:100%;margin:0">{rows}</table></div>'
    if kind == "chart":
        chart = shape.chart
        label = chart.chart_title.text_frame.text if chart.has_title else "Chart"
        return f'<div class="shape" style="{box}"><span class="chart">{escape(label)}</span></div>'
    if not getattr(shape, "has_text_frame", False) or not shape.has_text_frame or not shape.text_frame.text.strip():
        return ""
    sizes = [run.font.size.pt for paragraph in shape.text_frame.paragraphs for run in paragraph.runs if run.font.size]
    font = f";font-size:{max(8.0, sizes[0] * 0.75):.0f}px" if sizes else ""
    weight = ";font-weight:600" if shape.is_placeholder and "title" in str(shape.placeholder_format.type).lower() else ""
    return f'<div class="shape" style="{box}{font}{weight}">{escape(shape.text_frame.text)}</div>'


def slides_html(presentation: Any, title: str) -> str:
    width, height = presentation.slide_width, presentation.slide_height
    ratio = height / width * 100
    chunks: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        shapes = "".join(_shape_html(shape, width, height) for shape in slide.shapes)
        chunks.append(
            f'<div class="slide-label">Slide {index} · {escape(slide.slide_layout.name)}</div>'
            f'<div class="slide" style="max-width:960px"><div style="padding-top:{ratio:.2f}%"></div>{shapes}</div>'
        )
    return _page(title, "".join(chunks))


def document_html(kind: str, document: Any, title: str) -> str:
    if kind == "docx":
        return word_html(document, title)
    if kind == "pptx":
        return slides_html(document, title)
    return sheets_html(document, title)


__all__ = ["document_html", "sheets_html", "slides_html", "word_html"]
