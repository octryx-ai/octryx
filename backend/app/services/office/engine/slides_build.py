"""PowerPoint builders: slides (by layout or as a clone), shapes, connectors, tables, charts, pictures."""

from __future__ import annotations

import copy
from typing import Any

from lxml import etree
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR
from pptx.oxml.ns import qn
from pptx.parts.chart import ChartPart
from pptx.shapes.autoshape import AutoShapeType

from .charts import add_pptx_chart, chart_spec
from .paths import EMU_PER_CM, INVALID_REQUEST, UNSUPPORTED_ELEMENT, OfficeEngineError, length_emu
from .slides import Node, shape_paths
from .slides_format import apply_fill_line, apply_text_props, set_text

#: ``ST_LineEndType``: the only values a line end may carry.
LINE_END_TYPES = frozenset({"none", "triangle", "stealth", "diamond", "oval", "arrow"})
ADDABLE = ("slide", "shape", "textbox", "connector", "table", "chart", "picture")
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _shape_kinds() -> dict[str, Any]:
    kinds: dict[str, Any] = {}
    for member in MSO_AUTO_SHAPE_TYPE:
        try:
            kinds[AutoShapeType(member).prst.lower()] = member
        except KeyError:
            continue
        kinds[member.name.lower()] = member
    kinds["rect"] = MSO_AUTO_SHAPE_TYPE.RECTANGLE
    return kinds


_SHAPE_KINDS = _shape_kinds()


def find_layout(presentation: Any, requested: Any) -> Any:
    layouts = [layout for master in presentation.slide_masters for layout in master.slide_layouts]
    if requested in (None, ""):
        return layouts[1] if len(layouts) > 1 else layouts[0]
    text = str(requested).strip()
    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(layouts):
            return layouts[index - 1]
    wanted = text.replace(" ", "").lower()
    for layout in layouts:
        if str(layout.name).replace(" ", "").lower() == wanted:
            return layout
    names = ", ".join(sorted({str(layout.name) for layout in layouts}))
    raise OfficeEngineError(INVALID_REQUEST, f"unknown layout {text!r}; available: {names}")


def move_slide(presentation: Any, slide: Any, index: int | None) -> None:
    if not index:
        return
    slide_ids = presentation.slides._sldIdLst
    element = next(item for item in slide_ids if presentation.part.related_part(item.rId) is slide.part)
    slide_ids.remove(element)
    slide_ids.insert(max(0, min(index - 1, len(slide_ids))), element)


def add_slide(presentation: Any, *, layout: Any = None, title: str = "", index: int | None = None) -> Any:
    slide = presentation.slides.add_slide(find_layout(presentation, layout))
    if title and slide.shapes.title is not None:
        set_text(slide.shapes.title.text_frame, title)
    move_slide(presentation, slide, index)
    return slide


def _copy_chart_part(part: Any, package: Any) -> Any:
    partname = package.next_partname(ChartPart.partname_template)
    clone = ChartPart.load(partname, part.content_type, package, part.blob)
    for rel in part.rels.values():
        if not rel.is_external:
            clone.relate_to(rel.target_part, rel.reltype)
    return clone


def clone_slide(presentation: Any, source: Any, *, index: int | None = None) -> Any:
    slide = presentation.slides.add_slide(source.slide_layout)
    tree = slide.shapes._spTree
    for shape in list(slide.shapes):
        tree.remove(shape._element)
    rid_map: dict[str, str] = {}
    for rid, rel in source.part.rels.items():
        reltype = rel.reltype.rsplit("/", 1)[-1]
        if reltype in {"slideLayout", "notesSlide"}:
            continue
        if rel.is_external:
            rid_map[rid] = slide.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
            continue
        target = _copy_chart_part(rel.target_part, presentation.part.package) if reltype == "chart" else rel.target_part
        rid_map[rid] = slide.part.relate_to(target, rel.reltype)
    tail = tree.find(qn("p:extLst"))
    for element in source.shapes._spTree.iterchildren():
        if etree.QName(element).localname in {"nvGrpSpPr", "grpSpPr", "extLst"}:
            continue
        clone = copy.deepcopy(element)
        for node in clone.iter():
            for attribute, value in list(node.attrib.items()):
                if attribute.startswith(f"{{{_R_NS}}}") and value in rid_map:
                    node.set(attribute, rid_map[value])
        if tail is not None:
            tail.addprevious(clone)
        else:
            tree.append(clone)
    background = source._element.cSld.bg
    if background is not None:
        slide._element.cSld.insert(0, copy.deepcopy(background))
    move_slide(presentation, slide, index)
    return slide


def _box(props: dict[str, Any], *, x: str, y: str, width: str, height: str) -> tuple[int, int, int, int]:
    return (
        length_emu(props.get("x") or x),
        length_emu(props.get("y") or y),
        length_emu(props.get("width") or width),
        length_emu(props.get("height") or height),
    )


def add_shape(slide: Any, props: dict[str, Any], *, textbox: bool = False) -> Any:
    x, y, cx, cy = _box(props, x="2cm", y="2cm", width="8cm", height="3cm")
    if textbox:
        shape = slide.shapes.add_textbox(x, y, cx, cy)
        shape.text_frame.word_wrap = True
    else:
        preset = str(props.get("preset") or props.get("shape") or "rect").strip().lower()
        if preset not in _SHAPE_KINDS:
            raise OfficeEngineError(INVALID_REQUEST, f"unknown shape preset {preset!r}")
        shape = slide.shapes.add_shape(_SHAPE_KINDS[preset], x, y, cx, cy)
    if "name" in props:
        shape.name = str(props["name"])
    apply_fill_line(shape, props)
    if str(props.get("text") or ""):
        apply_text_props(shape.text_frame, props)
    return shape


def add_connector(slide: Any, props: dict[str, Any]) -> Any:
    x, y, cx, cy = _box(props, x="2cm", y="2cm", width="4cm", height="0cm")
    connector = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x, y, x + cx, y + cy)
    apply_fill_line(connector, {"line": props.get("line", "000000"), **{k: v for k, v in props.items() if k != "fill"}})
    for end in ("headEnd", "tailEnd"):
        value = str(props.get(end) or props.get(end.replace("End", "_end")) or "").strip()
        if value and value not in LINE_END_TYPES:
            raise OfficeEngineError(INVALID_REQUEST, f"{end} must be one of: {', '.join(sorted(LINE_END_TYPES))}")
        if value:
            line = connector.line._get_or_add_ln()
            line.append(etree.fromstring(f'<a:{end} xmlns:a="{_A_NS}" type="{value}"/>'))
    return connector


def add_table(slide: Any, props: dict[str, Any]) -> Any:
    headers = [str(item) for item in props.get("headers") or []] if isinstance(props.get("headers"), list) else []
    data = props.get("data") if isinstance(props.get("data"), list) else props.get("rows")
    body = [row for row in data if isinstance(row, list)] if isinstance(data, list) else []
    cols = max(int(props.get("cols") or 0), len(headers), max((len(row) for row in body), default=0))
    rows = max(int(props.get("rows") or 0) if not isinstance(props.get("rows"), list) else 0, len(body) + (1 if headers else 0))
    if rows < 1 or cols < 1:
        raise OfficeEngineError(INVALID_REQUEST, "a table needs at least one row and one column")
    x, y, cx, cy = _box(props, x="2cm", y="4.6cm", width="20.5cm", height=f"{min(rows, 12) * 0.9:.1f}cm")
    frame = slide.shapes.add_table(rows, cols, x, y, cx, cy)
    table = frame.table
    offset = 0
    if headers:
        for column, value in enumerate(headers):
            table.cell(0, column).text = value
        offset = 1
    for r, row in enumerate(body):
        for column, value in enumerate(row[:cols]):
            table.cell(r + offset, column).text = "" if value is None else str(value)
    size = props.get("size")
    if size:
        for row in table.rows:
            for cell in row.cells:
                apply_text_props(cell.text_frame, {"size": size})
    return frame


def add_chart(slide: Any, props: dict[str, Any]) -> Any:
    x, y, cx, cy = _box(props, x="2cm", y="4.4cm", width="20.5cm", height="9.5cm")
    return add_pptx_chart(slide.shapes, chart_spec(props), x=x, y=y, cx=cx, cy=cy)


def add_picture(slide: Any, props: dict[str, Any]) -> Any:
    path = str(props.get("path") or "").strip()
    if not path:
        raise OfficeEngineError(INVALID_REQUEST, "a picture needs a path")
    x = length_emu(props.get("x") or "2cm")
    y = length_emu(props.get("y") or "2cm")
    width = length_emu(props["width"]) if props.get("width") else None
    height = length_emu(props["height"]) if props.get("height") else None
    picture = slide.shapes.add_picture(path, x, y, width, height)
    if props.get("alt"):
        picture._element.xpath("./p:nvPicPr/p:cNvPr")[0].set("descr", str(props["alt"]))
    return picture


def add(presentation: Any, parent: Node, element_type: str, props: dict[str, Any], *,
        from_slide: Any = None, index: int | None = None) -> str:
    kind = element_type.strip().lower()
    if kind not in ADDABLE:
        raise OfficeEngineError(UNSUPPORTED_ELEMENT, f"PowerPoint supports: {', '.join(ADDABLE)}")
    if kind == "slide":
        if parent.kind != "presentation":
            raise OfficeEngineError(INVALID_REQUEST, "slides are added to /")
        if from_slide is not None:
            slide = clone_slide(presentation, from_slide, index=index)
        else:
            slide = add_slide(presentation, layout=props.get("layout"), title=str(props.get("title") or ""), index=index)
        return f"/slide[{list(presentation.slides).index(slide) + 1}]"
    if parent.kind != "slide":
        raise OfficeEngineError(INVALID_REQUEST, "shapes are added to a /slide[n] path")
    builders = {
        "shape": lambda: add_shape(parent.obj, props),
        "textbox": lambda: add_shape(parent.obj, props, textbox=True),
        "connector": lambda: add_connector(parent.obj, props),
        "table": lambda: add_table(parent.obj, props),
        "chart": lambda: add_chart(parent.obj, props),
        "picture": lambda: add_picture(parent.obj, props),
    }
    created = builders[kind]()
    return next(path for path, shape in shape_paths(parent.obj, parent.path) if shape._element is created._element)


def slide_size_cm(presentation: Any) -> tuple[float, float]:
    return presentation.slide_width / EMU_PER_CM, presentation.slide_height / EMU_PER_CM


__all__ = [
    "ADDABLE",
    "add",
    "add_chart",
    "add_connector",
    "add_picture",
    "add_shape",
    "add_slide",
    "add_table",
    "clone_slide",
    "find_layout",
    "move_slide",
    "slide_size_cm",
]
