"""PowerPoint descriptors (python-pptx): what ``get`` and ``query`` report for slides, shapes and text."""

from __future__ import annotations

from typing import Any

from .slides import Node, shape_paths, shape_type, typed_shapes


def slide_title(slide: Any) -> str:
    title = slide.shapes.title
    return title.text_frame.text.strip() if title is not None and title.has_text_frame else ""


def shape_descriptor(shape: Any, path: str) -> dict[str, Any]:
    kind = shape_type(shape)
    descriptor: dict[str, Any] = {
        "type": kind,
        "path": path,
        "name": shape.name,
        "text": shape.text_frame.text if getattr(shape, "has_text_frame", False) and shape.has_text_frame else "",
        "x": shape.left,
        "y": shape.top,
        "width": shape.width,
        "height": shape.height,
    }
    if shape.is_placeholder:
        descriptor["placeholder"] = str(shape.placeholder_format.type).split(" ")[0].split(".")[-1].lower()
        descriptor["placeholder_idx"] = shape.placeholder_format.idx
    if kind == "table":
        table = shape.table
        descriptor.update(rows=len(table.rows), cols=len(table.columns),
                          text="\n".join(" | ".join(cell.text for cell in row.cells) for row in table.rows))
    elif kind == "chart":
        chart = shape.chart
        descriptor.update(chart_type=str(chart.chart_type).split(" ")[0],
                          title=chart.chart_title.text_frame.text if chart.has_title else "",
                          series=[series.name for series in chart.plots[0].series] if chart.plots else [])
    elif kind == "picture":
        descriptor["alt"] = shape._element.xpath("./p:nvPicPr/p:cNvPr/@descr")[0] if shape._element.xpath(
            "./p:nvPicPr/p:cNvPr/@descr") else ""
    return descriptor


def slide_descriptor(slide: Any, path: str) -> dict[str, Any]:
    grouped = typed_shapes(slide)
    notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide and slide.notes_slide.notes_text_frame else ""
    return {
        "type": "slide",
        "path": path,
        "index": int(path.rsplit("[", 1)[-1].rstrip("]")),
        "layout": slide.slide_layout.name,
        "title": slide_title(slide),
        "text": "\n".join(shape.text_frame.text for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.has_text_frame),
        "notes": notes,
        **{f"{name}s": len(items) for name, items in grouped.items()},
    }


def describe(node: Node, depth: int) -> dict[str, Any]:
    if node.kind == "presentation":
        slides = list(node.obj.slides)
        result: dict[str, Any] = {"type": "presentation", "path": "/", "slides": len(slides),
                                  "slide_width": node.obj.slide_width, "slide_height": node.obj.slide_height,
                                  "layouts": [layout.name for layout in node.obj.slide_layouts]}
        if depth > 1:
            result["children"] = [describe(Node("slide", f"/slide[{i}]", s, s), depth - 1) for i, s in enumerate(slides, start=1)]
        return result
    if node.kind == "slide":
        result = slide_descriptor(node.obj, node.path)
        if depth > 1:
            result["children"] = [shape_descriptor(shape, path) for path, shape in shape_paths(node.obj, node.path)]
        return result
    if node.kind == "notes":
        return {"type": "notes", "path": node.path, "text": node.obj.notes_text_frame.text if node.obj.notes_text_frame else ""}
    if node.kind == "row":
        return {"type": "row", "path": node.path, "text": " | ".join(cell.text for cell in node.obj.cells)}
    if node.kind == "cell":
        return {"type": "cell", "path": node.path, "text": node.obj.text}
    if node.kind == "paragraph":
        runs = node.obj.runs
        return {"type": "paragraph", "path": node.path, "text": "".join(run.text for run in runs), "level": node.obj.level,
                "size": runs[0].font.size.pt if runs and runs[0].font.size else None}
    result = shape_descriptor(node.obj, node.path)
    if depth > 1 and node.kind == "group":
        result["children"] = [shape_descriptor(shape, f"{node.path}/{shape_type(shape)}") for shape in node.obj.shapes]
    return result


def iter_descriptors(presentation: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for index, slide in enumerate(presentation.slides, start=1):
        slide_path = f"/slide[{index}]"
        found.append(slide_descriptor(slide, slide_path))
        for path, shape in shape_paths(slide, slide_path):
            found.append(shape_descriptor(shape, path))
            if shape_type(shape) == "table":
                for r, row in enumerate(shape.table.rows, start=1):
                    for c, cell in enumerate(row.cells, start=1):
                        found.append({"type": "cell", "path": f"{path}/tr[{r}]/tc[{c}]", "text": cell.text})
    return found


__all__ = [
    "describe",
    "iter_descriptors",
    "shape_descriptor",
    "slide_descriptor",
    "slide_title",
]
