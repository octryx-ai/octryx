"""PowerPoint presentations (python-pptx): element paths, property edits, removal (descriptors: ``slides_describe``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pptx.dml.color import RGBColor

from .charts import chart_spec, pptx_chart_data
from .paths import (
    ELEMENT_NOT_FOUND,
    UNSUPPORTED_ELEMENT,
    OfficeEngineError,
    Segment,
    hex_color,
)
from .slides_format import apply_fill_line, apply_font, apply_geometry, apply_text_props, set_paragraph_text, set_text

SHAPE_TYPES = ("shape", "picture", "table", "chart", "connector", "group", "frame")


@dataclass(slots=True)
class Node:
    kind: str
    path: str
    obj: Any
    slide: Any = None


def shape_type(shape: Any) -> str:
    tag = shape._element.tag.rsplit("}", 1)[-1]
    if tag == "sp":
        return "shape"
    if tag == "pic":
        return "picture"
    if tag == "cxnSp":
        return "connector"
    if tag == "grpSp":
        return "group"
    if getattr(shape, "has_table", False) and shape.has_table:
        return "table"
    if getattr(shape, "has_chart", False) and shape.has_chart:
        return "chart"
    return "frame"


def typed_shapes(slide: Any) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {name: [] for name in SHAPE_TYPES}
    for shape in slide.shapes:
        grouped[shape_type(shape)].append(shape)
    return grouped


def shape_paths(slide: Any, slide_path: str) -> list[tuple[str, Any]]:
    counts: dict[str, int] = {}
    found: list[tuple[str, Any]] = []
    for shape in slide.shapes:
        kind = shape_type(shape)
        counts[kind] = counts.get(kind, 0) + 1
        found.append((f"{slide_path}/{kind}[{counts[kind]}]", shape))
    return found


def _pick(items: list[Any], segment: Segment, path: str) -> Any:
    index = segment.index or 1
    if index > len(items):
        raise OfficeEngineError(ELEMENT_NOT_FOUND, path)
    return items[index - 1]


def resolve(presentation: Any, segments: list[Segment]) -> Node:
    node = Node("presentation", "/", presentation)
    for segment in segments:
        path = f"{node.path.rstrip('/')}/{segment.name}" + ("" if segment.name == "notes" else f"[{segment.index or 1}]")
        if node.kind == "presentation" and segment.name == "slide":
            slide = _pick(list(presentation.slides), segment, path)
            node = Node("slide", path, slide, slide)
        elif node.kind == "slide" and segment.name == "notes":
            node = Node("notes", path, node.obj.notes_slide, node.slide)
        elif node.kind == "slide" and segment.name in SHAPE_TYPES:
            node = Node(segment.name, path, _pick(typed_shapes(node.obj)[segment.name], segment, path), node.slide)
        elif node.kind == "table" and segment.name == "tr":
            node = Node("row", path, _pick(list(node.obj.table.rows), segment, path), node.slide)
        elif node.kind == "row" and segment.name == "tc":
            node = Node("cell", path, _pick(list(node.obj.cells), segment, path), node.slide)
        elif node.kind in {"shape", "cell"} and segment.name == "p" and _has_text(node.obj):
            node = Node("paragraph", path, _pick(list(node.obj.text_frame.paragraphs), segment, path), node.slide)
        elif node.kind == "group" and segment.name in SHAPE_TYPES:
            members = [shape for shape in node.obj.shapes if shape_type(shape) == segment.name]
            node = Node(segment.name, path, _pick(members, segment, path), node.slide)
        else:
            raise OfficeEngineError(ELEMENT_NOT_FOUND, path)
    return node


def _has_text(obj: Any) -> bool:
    return bool(getattr(obj, "has_text_frame", True)) and hasattr(obj, "text_frame")


def set_props(node: Node, props: dict[str, Any]) -> None:
    kind, obj = node.kind, node.obj
    if kind == "slide":
        if "title" in props and obj.shapes.title is not None:
            set_text(obj.shapes.title.text_frame, str(props["title"]))
        if "notes" in props:
            obj.notes_slide.notes_text_frame.text = str(props["notes"])
        return
    if kind == "notes":
        obj.notes_text_frame.text = str(props.get("text", ""))
        return
    if kind == "paragraph":
        if "text" in props:
            set_paragraph_text(obj, str(props["text"]))
        if "level" in props:
            obj.level = int(props["level"])
        apply_font(obj.runs, props)
        return
    if kind == "cell":
        apply_text_props(obj.text_frame, props)
        if "fill" in props:
            obj.fill.solid()
            obj.fill.fore_color.rgb = RGBColor.from_string(hex_color(props["fill"]))
        return
    if kind == "chart":
        apply_geometry(obj, props)
        if any(key.startswith("series") or key == "data" for key in props):
            obj.chart.replace_data(pptx_chart_data(chart_spec({"chart_type": "column", **props})))
        if "title" in props:
            obj.chart.has_title = bool(str(props["title"]).strip())
            if obj.chart.has_title:
                obj.chart.chart_title.text_frame.text = str(props["title"])
        return
    if kind not in {"shape", "picture", "table", "connector", "group", "frame"}:
        raise OfficeEngineError(UNSUPPORTED_ELEMENT, f"cannot set properties on {kind}")
    apply_geometry(obj, props)
    if kind == "picture" and "alt" in props:
        obj._element.xpath("./p:nvPicPr/p:cNvPr")[0].set("descr", str(props["alt"]))
    if kind in {"shape", "connector"}:
        apply_fill_line(obj, props)
    if kind == "shape" and obj.has_text_frame:
        apply_text_props(obj.text_frame, props)


def remove_slide(presentation: Any, slide: Any) -> None:
    slide_ids = presentation.slides._sldIdLst
    for slide_id in list(slide_ids):
        if presentation.part.related_part(slide_id.rId) is slide.part:
            presentation.part.drop_rel(slide_id.rId)
            slide_ids.remove(slide_id)
            return
    raise OfficeEngineError(ELEMENT_NOT_FOUND, "slide")


def remove(presentation: Any, node: Node) -> None:
    if node.kind == "slide":
        remove_slide(presentation, node.obj)
        return
    if node.kind in {"shape", "picture", "table", "chart", "connector", "group", "frame"}:
        element = node.obj._element
        element.getparent().remove(element)
        return
    if node.kind == "paragraph":
        element = node.obj._p
        if len(element.getparent().findall(element.tag)) == 1:
            raise OfficeEngineError(UNSUPPORTED_ELEMENT, "a text frame keeps at least one paragraph")
        element.getparent().remove(element)
        return
    raise OfficeEngineError(UNSUPPORTED_ELEMENT, f"{node.kind} cannot be removed")


__all__ = [
    "SHAPE_TYPES",
    "Node",
    "remove",
    "remove_slide",
    "resolve",
    "set_props",
    "shape_paths",
    "shape_type",
    "typed_shapes",
]
