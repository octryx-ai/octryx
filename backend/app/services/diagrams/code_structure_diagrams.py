"""Deterministic diagram builders backed by ``code_structure_snapshot`` evidence.

Every class, member, and relation rendered here is copied verbatim from the
snapshot's ``diagram_brief`` (which itself only carries literal declarations).
No members are invented and no relations are guessed.
"""

from __future__ import annotations

from typing import Any

from .diagram_styles import edge_style, uml_class_container_style, uml_class_row_style
from .models import DiagramEdgeIR, DiagramIR, DiagramNodeIR

_MAX_CLASS_NODES = 8
_CLASS_COLUMNS = 3
_CLASS_WIDTH = 230
_COLUMN_PITCH = 320
_ROW_HEIGHT = 22
_HEADER_HEIGHT = 36
_DIVIDER_HEIGHT = 16


def snapshot_diagram_brief(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    brief = snapshot.get("diagram_brief")
    return brief if isinstance(brief, dict) else {}


def _wired_refs(snapshot: dict[str, Any] | None) -> set[str]:
    """Refs participating in renderable relations (extends/implements/uses)."""
    refs: set[str] = set()
    for edge in snapshot_diagram_brief(snapshot).get("selected_edges") or []:
        if isinstance(edge, dict) and str(edge.get("type") or "") in {"extends", "implements", "uses"}:
            refs.add(str(edge.get("source_ref") or ""))
            refs.add(str(edge.get("target_ref") or ""))
    return refs


def snapshot_class_entries(
    snapshot: dict[str, Any] | None, *, max_classes: int = _MAX_CLASS_NODES
) -> list[dict[str, Any]]:
    """Class/interface/enum nodes from the brief, bounded.

    Nodes participating in renderable relations come first (brief order kept
    within each group): a first-N cut of an alphabetical brief produced
    edge-less diagrams whenever the wired nodes sorted past the cap.
    """
    wired = _wired_refs(snapshot)
    candidates = [
        node
        for node in snapshot_diagram_brief(snapshot).get("selected_nodes") or []
        if isinstance(node, dict) and str(node.get("type") or "") != "package"
    ]
    ordered = [node for node in candidates if str(node.get("ref") or "") in wired] + [
        node for node in candidates if str(node.get("ref") or "") not in wired
    ]
    entries: list[dict[str, Any]] = []
    for node in ordered:
        label = str(node.get("label") or "").strip()
        ref = str(node.get("ref") or "").strip()
        if not label or not ref:
            continue
        attributes = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
        entries.append(
            {
                "ref": ref,
                "label": label,
                "kind": str(node.get("type") or "class"),
                "package": str(attributes.get("package") or ""),
                "fields": [str(item) for item in (attributes.get("fields") or []) if str(item).strip()],
                "methods": [str(item) for item in (attributes.get("methods") or []) if str(item).strip()],
            }
        )
        if len(entries) >= max_classes:
            break
    return entries


def snapshot_has_renderable_classes(snapshot: dict[str, Any] | None) -> bool:
    return bool(snapshot_class_entries(snapshot, max_classes=1))


def snapshot_edges_between(snapshot: dict[str, Any] | None, refs: set[str]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for edge in snapshot_diagram_brief(snapshot).get("selected_edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source_ref") or "")
        target = str(edge.get("target_ref") or "")
        edge_type = str(edge.get("type") or "")
        if source in refs and target in refs and edge_type in {"extends", "implements", "uses"}:
            edges.append({"source_ref": source, "target_ref": target, "type": edge_type})
    return edges


def _class_container_height(entry: dict[str, Any]) -> int:
    member_rows = len(entry["fields"]) + len(entry["methods"])
    return _HEADER_HEIGHT + member_rows * _ROW_HEIGHT + _DIVIDER_HEIGHT + 12


def _append_member_rows(
    nodes: list[DiagramNodeIR], entry: dict[str, Any], class_id: str, row_style: str, divider_style: str
) -> None:
    for index, field in enumerate(entry["fields"], start=1):
        nodes.append(
            DiagramNodeIR(
                f"{class_id}_a{index}",
                field,
                row_style,
                0,
                _HEADER_HEIGHT + (index - 1) * _ROW_HEIGHT,
                _CLASS_WIDTH - 20,
                20,
                parent=class_id,
            )
        )
    divider_y = _HEADER_HEIGHT + len(entry["fields"]) * _ROW_HEIGHT
    nodes.append(
        DiagramNodeIR(
            f"{class_id}_divider",
            "----------------",
            divider_style,
            0,
            divider_y,
            _CLASS_WIDTH - 20,
            _DIVIDER_HEIGHT,
            parent=class_id,
        )
    )
    for index, method in enumerate(entry["methods"], start=1):
        nodes.append(
            DiagramNodeIR(
                f"{class_id}_m{index}",
                method,
                row_style,
                0,
                divider_y + _DIVIDER_HEIGHT + (index - 1) * _ROW_HEIGHT,
                _CLASS_WIDTH - 20,
                20,
                parent=class_id,
            )
        )


def _class_label(entry: dict[str, Any]) -> str:
    kind = entry["kind"]
    if kind in {"interface", "enum"}:
        return f"<<{kind}>>\n{entry['label']}"
    return entry["label"]


def build_uml_class_diagram_ir_from_snapshot(
    workflow_contract: dict[str, Any], snapshot: dict[str, Any]
) -> DiagramIR:
    title = str(workflow_contract.get("topic") or "UML Class Diagram").strip()
    entries = snapshot_class_entries(snapshot)
    divider_style = (
        "text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontSize=10;fontColor=#999999;"
    )
    nodes: list[DiagramNodeIR] = []
    id_by_ref: dict[str, str] = {}
    row_heights: dict[int, int] = {}
    for index, entry in enumerate(entries):
        row_heights[index // _CLASS_COLUMNS] = max(
            row_heights.get(index // _CLASS_COLUMNS, 0), _class_container_height(entry)
        )
    for index, entry in enumerate(entries):
        class_id = f"uml_c{index + 1}"
        id_by_ref[entry["ref"]] = class_id
        column = index % _CLASS_COLUMNS
        row = index // _CLASS_COLUMNS
        y = 110 + sum(row_heights[prior] + 70 for prior in range(row))
        nodes.append(
            DiagramNodeIR(
                class_id,
                _class_label(entry),
                uml_class_container_style(),
                110 + column * _COLUMN_PITCH,
                y,
                _CLASS_WIDTH,
                _class_container_height(entry),
            )
        )
        _append_member_rows(nodes, entry, class_id, uml_class_row_style(), divider_style)
    edges = tuple(
        DiagramEdgeIR(
            f"uml_e{index + 1}",
            id_by_ref[edge["source_ref"]],
            id_by_ref[edge["target_ref"]],
            label=edge["type"],
            style=edge_style(dashed=edge["type"] != "extends"),
        )
        for index, edge in enumerate(snapshot_edges_between(snapshot, set(id_by_ref)))
    )
    return DiagramIR(title=title, renderer="uml_class", notation="uml_class", nodes=tuple(nodes), edges=edges)


def build_code_structure_class_diagram_tool_call(
    snapshot: dict[str, Any], allowed_tool_names: set[str] | None, *, title: str
) -> list[dict[str, Any]]:
    """The deterministic class diagram of a code-structure snapshot as one ``create_diagram`` call.

    Same discipline as the AWS topology renders: every deterministic render passes the geometry
    quality gate before it reaches ``create_diagram``.
    """
    from ..turn_tool_history import _build_tool_call
    from .aws_diagram_quality_gate import apply_quality_gate
    from .renderers import render_diagram_ir

    diagram = build_uml_class_diagram_ir_from_snapshot({"topic": title}, snapshot)
    return _build_tool_call(
        "create_diagram",
        {"title": diagram.title, "xml": apply_quality_gate(render_diagram_ir(diagram))},
        allowed_tool_names,
    )
