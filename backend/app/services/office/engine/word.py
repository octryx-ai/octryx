"""Word documents (python-docx): element paths, descriptors (``word_descriptors``), edits (``word_props``).

Paths: ``/body``, ``/body/p[n]``, ``/body/tbl[n]``, ``/body/tbl[n]/tr[r]/tc[c]`` (and ``…/tc[c]/p[n]``),
``/body/p[n]/r[k]``, ``/body/sdt[n]`` (content controls, document order).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .paths import (
    ELEMENT_NOT_FOUND,
    INVALID_REQUEST,
    UNSUPPORTED_ELEMENT,
    OfficeEngineError,
    Segment,
    hex_color,
)
from .word_descriptors import (
    body_blocks,
    content_control_descriptor,
    paragraph_descriptor,
    run_descriptor,
    table_text,
)
from .word_props import apply_paragraph_props, apply_run_props, find_style, set_paragraph_text

ADDABLE = ("paragraph", "heading", "list_item", "run", "table", "picture", "page_break", "toc", "equation", "chart")


@dataclass(slots=True)
class Node:
    kind: str
    path: str
    obj: Any


# --- paths -------------------------------------------------------------------------------------------------


def _children(element: Any, tag: str) -> list[Any]:
    return [child for child in element.iterchildren(qn(f"w:{tag}"))]


def _pick(items: list[Any], segment: Segment, path: str) -> Any:
    index = segment.index or 1
    if index > len(items):
        raise OfficeEngineError(ELEMENT_NOT_FOUND, path)
    return items[index - 1]


def resolve(document: Any, segments: list[Segment]) -> Node:
    if not segments or segments[0].name != "body":
        raise OfficeEngineError(ELEMENT_NOT_FOUND, "Word paths start with /body")
    node = Node("body", "/body", document)
    for segment in segments[1:]:
        path = f"{node.path}/{segment.name}[{segment.index or 1}]"
        container = document.element.body if node.kind == "body" else getattr(node.obj, "_element", None)
        if node.kind in {"body", "cell"} and segment.name == "p":
            node = Node("paragraph", path, Paragraph(_pick(_children(container, "p"), segment, path), node.obj))
        elif node.kind in {"body", "cell"} and segment.name == "tbl":
            node = Node("table", path, Table(_pick(_children(container, "tbl"), segment, path), node.obj))
        elif node.kind == "body" and segment.name == "sdt":
            node = Node("content_control", path, _pick(list(container.iter(qn("w:sdt"))), segment, path))
        elif node.kind == "table" and segment.name == "tr":
            node = Node("row", path, _pick(list(node.obj.rows), segment, path))
        elif node.kind == "row" and segment.name == "tc":
            node = Node("cell", path, _pick(list(node.obj.cells), segment, path))
        elif node.kind == "paragraph" and segment.name == "r":
            node = Node("run", path, _pick(list(node.obj.runs), segment, path))
        else:
            raise OfficeEngineError(ELEMENT_NOT_FOUND, path)
    return node


# --- descriptors -------------------------------------------------------------------------------------------


def describe(node: Node, depth: int) -> dict[str, Any]:
    kind, obj, path = node.kind, node.obj, node.path
    if kind == "body":
        blocks = body_blocks(obj)
        result: dict[str, Any] = {"type": "body", "path": path, "children_count": len(blocks)}
        if depth > 1:
            result["children"] = [
                describe(Node(block_kind, block_path, block), depth - 1) for block_kind, block_path, block in blocks
            ]
        return result
    if kind == "paragraph":
        result = paragraph_descriptor(obj, path)
        if depth > 1:
            result["children"] = [run_descriptor(run, f"{path}/r[{i}]") for i, run in enumerate(obj.runs, start=1)]
        return result
    if kind == "run":
        return run_descriptor(obj, path)
    if kind == "table":
        result = {
            "type": "table",
            "path": path,
            "rows": len(obj.rows),
            "cols": len(obj.columns),
            "style": getattr(obj.style, "name", None),
            "text": table_text(obj),
        }
        if depth > 1:
            result["children"] = [
                describe(Node("row", f"{path}/tr[{i}]", row), depth - 1) for i, row in enumerate(obj.rows, start=1)
            ]
        return result
    if kind == "row":
        result = {"type": "row", "path": path, "cells": len(obj.cells), "text": " | ".join(c.text for c in obj.cells)}
        if depth > 1:
            result["children"] = [
                describe(Node("cell", f"{path}/tc[{i}]", cell), depth - 1) for i, cell in enumerate(obj.cells, start=1)
            ]
        return result
    if kind == "cell":
        result = {"type": "cell", "path": path, "text": obj.text}
        if depth > 1:
            result["children"] = [
                paragraph_descriptor(p, f"{path}/p[{i}]") for i, p in enumerate(obj.paragraphs, start=1)
            ]
        return result
    return content_control_descriptor(obj, path)


def iter_descriptors(document: Any) -> list[dict[str, Any]]:
    """Every addressable element, flat, for selectors."""
    found: list[dict[str, Any]] = []
    for kind, path, block in body_blocks(document):
        if kind == "paragraph":
            found.append(paragraph_descriptor(block, path))
            found.extend(run_descriptor(run, f"{path}/r[{i}]") for i, run in enumerate(block.runs, start=1))
            continue
        found.append(describe(Node("table", path, block), 1))
        for r, row in enumerate(block.rows, start=1):
            for c, cell in enumerate(row.cells, start=1):
                cell_path = f"{path}/tr[{r}]/tc[{c}]"
                found.append({"type": "cell", "path": cell_path, "text": cell.text})
                found.extend(
                    paragraph_descriptor(p, f"{cell_path}/p[{i}]") for i, p in enumerate(cell.paragraphs, start=1)
                )
    for index, sdt in enumerate(document.element.body.iter(qn("w:sdt")), start=1):
        found.append(content_control_descriptor(sdt, f"/body/sdt[{index}]"))
    return found


# --- edits -------------------------------------------------------------------------------------------------



def _shade(cell: Any, color: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    for existing in properties.findall(qn("w:shd")):
        properties.remove(existing)
    properties.append(parse_xml(f'<w:shd xmlns:w="{_W}" w:val="clear" w:color="auto" w:fill="{hex_color(color)}"/>'))


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def set_props(document: Any, node: Node, props: dict[str, Any]) -> None:
    if node.kind == "paragraph":
        apply_paragraph_props(document, node.obj, props)
    elif node.kind == "run":
        if "text" in props:
            node.obj.text = str(props["text"])
        apply_run_props(node.obj, props)
    elif node.kind == "cell":
        if "text" in props:
            set_paragraph_text(node.obj.paragraphs[0], str(props["text"]))
            for extra in node.obj.paragraphs[1:]:
                extra._p.getparent().remove(extra._p)
        if "fill" in props:
            _shade(node.obj, props["fill"])
        paragraph_props = {key: value for key, value in props.items() if key not in {"text", "fill"}}
        for paragraph in node.obj.paragraphs:
            apply_paragraph_props(document, paragraph, paragraph_props)
    elif node.kind == "table":
        if "style" in props:
            node.obj.style = find_style(document, props["style"])
    elif node.kind == "content_control":
        texts = list(node.obj.iter(qn("w:t")))
        if not texts:
            raise OfficeEngineError(UNSUPPORTED_ELEMENT, "content control has no text run")
        texts[0].text = str(props.get("text", props.get("value", "")))
        for extra in texts[1:]:
            extra.text = ""
    else:
        raise OfficeEngineError(UNSUPPORTED_ELEMENT, f"cannot set properties on {node.kind}")


def remove(node: Node) -> None:
    # lxml elements without children are falsy, so the element is picked per kind, never with ``or``.
    elements = {
        "paragraph": lambda: node.obj._p,
        "table": lambda: node.obj._tbl,
        "row": lambda: node.obj._tr,
        "cell": lambda: node.obj._tc,
        "run": lambda: node.obj._r,
        "content_control": lambda: node.obj,
    }
    if node.kind not in elements:
        raise OfficeEngineError(UNSUPPORTED_ELEMENT, f"{node.kind} cannot be removed")
    element = elements[node.kind]()
    parent = element.getparent()
    parent.remove(element)
    if parent.tag == qn("w:tc") and parent.find(qn("w:p")) is None:
        parent.append(parse_xml(f'<w:p xmlns:w="{_W}"/>'))


def _place(element: Any, container: Any, index: int | None) -> None:
    """Move a freshly appended block to 1-based ``index`` among the container's paragraphs and tables."""
    if not index:
        return
    blocks = [
        child for child in container.iterchildren() if child.tag in {qn("w:p"), qn("w:tbl")} and child is not element
    ]
    if index <= len(blocks):
        blocks[index - 1].addprevious(element)


def add(document: Any, parent: Node, element_type: str, props: dict[str, Any], index: int | None) -> str:
    """Add an element; returns the new element's path."""
    from . import word_blocks

    kind = element_type.strip().lower()
    if kind not in ADDABLE:
        raise OfficeEngineError(UNSUPPORTED_ELEMENT, f"Word supports: {', '.join(ADDABLE)}")
    if kind == "run":
        if parent.kind != "paragraph":
            raise OfficeEngineError(INVALID_REQUEST, "runs are added to a paragraph path")
        run = parent.obj.add_run(str(props.get("text") or ""))
        apply_run_props(run, props)
        return f"{parent.path}/r[{len(parent.obj.runs)}]"
    if parent.kind not in {"body", "cell"}:
        raise OfficeEngineError(INVALID_REQUEST, "blocks are added to /body or a table cell")
    container_obj = document if parent.kind == "body" else parent.obj
    container = document.element.body if parent.kind == "body" else parent.obj._tc
    element = word_blocks.add_block(document, container_obj, kind, props)
    _place(element, container, index)
    tag = "tbl" if element.tag == qn("w:tbl") else "p"
    position = 1 + sum(1 for sibling in element.itersiblings(preceding=True) if sibling.tag == element.tag)
    return f"{parent.path}/{tag}[{position}]"



__all__ = [
    "ADDABLE",
    "Node",
    "add",
    "describe",
    "iter_descriptors",
    "remove",
    "resolve",
    "set_props",
]
