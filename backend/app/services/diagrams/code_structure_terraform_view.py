"""Dedicated Terraform infrastructure views from ``code_structure_snapshot``.

Mirrors the AWS pattern (inventory board + detail set): the module overview
shows EVERY module directory as an inventory card (block counts by kind,
resource-type counters, provider counters — no container cap), and the top
modules by block count get their own detail diagram with real provider icons
and reference edges. The enforcement layer walks the set titles exactly like
the AWS detail set.

Everything rendered here is copied verbatim from the snapshot brief; selection
is deterministic and every bound is stated in the legend instead of being
silently applied. Provider icon mapping (aws4 shapes, Azure/GCP extension
point) lives in ``code_structure_terraform_icons``.
"""

from __future__ import annotations

from typing import Any

from .code_structure_diagrams import snapshot_diagram_brief
from .code_structure_terraform_icons import BOX_WIDTH, node_visual
from .models import DiagramEdgeIR, DiagramIR, DiagramNodeIR

_OVERVIEW_TITLE = "Terraform infrastructure - Module overview"
_DETAIL_TITLE_PREFIX = "Terraform infrastructure - "

_RENDERED_KINDS = ("resource", "data", "module")
_KIND_LABELS = {
    "resource": "resource",
    "data": "data source",
    "module": "module",
    "variable": "variable",
    "output": "output",
}

_MAX_OVERVIEW_CARDS = 60
_OVERVIEW_COLUMNS = 3
_CARD_W = 380
_CARD_GAP = 20
_CARD_LINE_H = 15
_CARD_BASE_H = 34
_MAX_CARD_TYPES = 5

_DETAIL_MIN_BLOCKS = 3
_MAX_DETAIL_DIAGRAMS = 4
_MAX_DETAIL_CHILDREN = 36  # + explicit tail node, still under the 40-child gate
_DETAIL_COLUMNS = 4
_CELL_PITCH_X = 170
_CELL_PITCH_Y = 118

_CARD_STYLE = (
    "rounded=1;arcSize=6;whiteSpace=wrap;html=1;fontSize=10;align=left;verticalAlign=top;"
    "spacing=8;fillColor=#ffffff;strokeColor=#64748b;fontColor=#1f2937;"
)
_CONTAINER_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;container=1;recursiveResize=0;collapsible=0;"
    "fillColor=#f8fafc;strokeColor=#64748b;align=left;verticalAlign=top;spacingLeft=12;"
    "fontStyle=1;fontSize=11;"
)
_TAIL_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=10;fontStyle=2;"
_LEGEND_STYLE = (
    "text;html=1;strokeColor=#999999;fillColor=#ffffff;align=left;verticalAlign=top;"
    "spacing=8;fontSize=10;rounded=1;"
)
_EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;"
    "endArrow=block;fontSize=9;strokeColor=#64748b;fontColor=#475569;"
)


def snapshot_is_terraform(snapshot: dict[str, Any] | None) -> bool:
    """Explicit signal only: the snapshot parsed at least one terraform file."""
    if not isinstance(snapshot, dict):
        return False
    summary = snapshot.get("service_summary")
    counts = summary.get("counts_by_language") if isinstance(summary, dict) else None
    return bool(isinstance(counts, dict) and counts.get("terraform"))


def _brief_nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in snapshot_diagram_brief(snapshot).get("selected_nodes") or [] if isinstance(node, dict)]


def _brief_uses_edges(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"source_ref": str(edge.get("source_ref") or ""), "target_ref": str(edge.get("target_ref") or "")}
        for edge in snapshot_diagram_brief(snapshot).get("selected_edges") or []
        if isinstance(edge, dict) and str(edge.get("type") or "") == "uses"
    ]


def _node_attributes(node: dict[str, Any]) -> dict[str, Any]:
    attributes = node.get("attributes")
    return attributes if isinstance(attributes, dict) else {}


def _module_groups(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """All brief block nodes (every kind) grouped by module directory."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for node in _brief_nodes(snapshot):
        if str(node.get("type") or "") == "package":
            continue
        groups.setdefault(str(_node_attributes(node).get("package") or ""), []).append(node)
    return groups


def _package_totals(snapshot: dict[str, Any]) -> dict[str, dict[str, int]]:
    """True per-module totals from the package nodes (module-quota core)."""
    totals: dict[str, dict[str, int]] = {}
    for node in _brief_nodes(snapshot):
        if str(node.get("type") or "") != "package":
            continue
        attributes = _node_attributes(node)
        totals[str(node.get("label") or "")] = {
            "class_count": int(attributes.get("class_count") or 0),
            "selected_count": int(attributes.get("selected_count") or 0),
        }
    return totals


def _common_package_prefix(packages: list[str]) -> str:
    """Longest common dotted prefix across non-empty package paths.

    Workspace clones nest the repo under long directory chains
    (``var.repos.bitbucket.<project>.<repo>...``); stripping the shared prefix
    keeps labels on the meaningful module directory while the legend states
    the stripped root explicitly.
    """
    non_empty = [package for package in packages if package]
    if not non_empty or len(non_empty) != len(packages):
        return ""
    split = [package.split(".") for package in non_empty]
    prefix_parts: list[str] = []
    for parts in zip(*split, strict=False):
        if all(part == parts[0] for part in parts):
            prefix_parts.append(parts[0])
        else:
            break
    # never strip a package down to nothing: keep at least one segment
    max_parts = min(len(parts) for parts in split) - 1
    prefix_parts = prefix_parts[:max_parts] if max_parts > 0 else []
    return ".".join(prefix_parts)


def _display_package(package: str, prefix: str) -> str:
    stripped = package[len(prefix) + 1 :] if prefix and package.startswith(prefix + ".") else package
    return stripped or "root module"


def _provider_counts(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        provider = str(_node_attributes(node).get("provider") or "")
        if provider:
            counts[provider] = counts.get(provider, 0) + 1
    return counts


def _kind_counts_line(nodes: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for node in nodes:
        kind = str(node.get("type") or "")
        if kind in _KIND_LABELS:
            counts[kind] = counts.get(kind, 0) + 1
    return ", ".join(
        f"{counts[kind]} {_KIND_LABELS[kind]}{'s' if counts[kind] != 1 else ''}"
        for kind in _KIND_LABELS
        if counts.get(kind)
    )


def _card_lines(package: str, nodes: list[dict[str, Any]], totals: dict[str, int], prefix: str) -> list[str]:
    total = totals.get("class_count") or len(nodes)
    header = f"{_display_package(package, prefix)} - {total} block{'s' if total != 1 else ''}"
    selected = totals.get("selected_count") or 0
    if selected and selected < total:
        header += f" (sampled {selected})"
    lines = [header]
    kinds = _kind_counts_line(nodes)
    if kinds:
        lines.append(kinds)
    providers = _provider_counts(nodes)
    if providers:
        lines.append("providers: " + ", ".join(f"{name} {count}" for name, count in sorted(providers.items())))
    type_counts: dict[str, int] = {}
    for node in nodes:
        resource_type = str(_node_attributes(node).get("resource_type") or "")
        if resource_type:
            type_counts[resource_type] = type_counts.get(resource_type, 0) + 1
    top_types = sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
    for resource_type, count in top_types[:_MAX_CARD_TYPES]:
        lines.append(f"{count} x {resource_type}")
    if len(top_types) > _MAX_CARD_TYPES:
        lines.append(f"+{len(top_types) - _MAX_CARD_TYPES} more types")
    return lines


def build_terraform_module_overview_ir(
    workflow_contract: dict[str, Any], snapshot: dict[str, Any]
) -> DiagramIR | None:
    """One inventory card per module directory — scales past any container cap."""
    title = str(workflow_contract.get("topic") or _OVERVIEW_TITLE).strip()
    groups = _module_groups(snapshot)
    if not groups:
        return None
    totals = _package_totals(snapshot)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    shown = ordered[:_MAX_OVERVIEW_CARDS]
    prefix = _common_package_prefix([package for package, _nodes in shown])

    nodes: list[DiagramNodeIR] = []
    all_nodes = [node for _package, group in groups.items() for node in group]
    provider_counts = _provider_counts(all_nodes)
    truncated = bool(snapshot_diagram_brief(snapshot).get("truncated"))
    legend_lines = [
        f"Module inventory from code_structure_snapshot: {len(groups)} module directories, "
        f"{len(all_nodes)} blocks in the brief"
        + (" (brief truncated - per-module totals below are authoritative)" if truncated else ""),
        "Providers: "
        + (", ".join(f"{name} {count}" for name, count in sorted(provider_counts.items())) or "none detected"),
    ]
    if len(ordered) > len(shown):
        legend_lines.append(f"Not shown: {len(ordered) - len(shown)} module directories (card bound)")
    if prefix:
        legend_lines.append(f"Module root (stripped from card labels): {prefix}")
    legend_lines.append("Counts are literal block declarations; details follow per top module")
    legend_height = 24 + len(legend_lines) * 14
    nodes.append(
        DiagramNodeIR(
            "tf_ov_legend",
            "\n".join(legend_lines),
            _LEGEND_STYLE,
            60,
            56,
            _OVERVIEW_COLUMNS * (_CARD_W + _CARD_GAP) - _CARD_GAP,
            legend_height,
        )
    )

    grid_top = 56 + legend_height + 24
    row_y = grid_top
    row_heights: list[int] = []
    for index, (package, group) in enumerate(shown):
        column = index % _OVERVIEW_COLUMNS
        if column == 0 and index > 0:
            row_y += max(row_heights) + _CARD_GAP
            row_heights = []
        lines = _card_lines(package, group, totals.get(package, {}), prefix)
        height = _CARD_BASE_H + len(lines) * _CARD_LINE_H
        row_heights.append(height)
        nodes.append(
            DiagramNodeIR(
                f"tf_card{index + 1}",
                "\n".join(lines),
                _CARD_STYLE,
                60 + column * (_CARD_W + _CARD_GAP),
                row_y,
                _CARD_W,
                height,
            )
        )
    return DiagramIR(title=title, renderer="node_link", notation="component", nodes=tuple(nodes), edges=())


def _ordered_module_refs(group: list[dict[str, Any]], wired: set[str]) -> list[dict[str, Any]]:
    rendered = [node for node in group if str(node.get("type") or "") in _RENDERED_KINDS]

    def _sort_key(node: dict[str, Any]) -> tuple[int, str, str]:
        attributes = _node_attributes(node)
        return (
            0 if str(node.get("ref") or "") in wired else 1,
            str(attributes.get("resource_type") or ""),
            str(node.get("label") or ""),
        )

    return sorted(rendered, key=_sort_key)


def build_terraform_module_detail_ir(
    workflow_contract: dict[str, Any], snapshot: dict[str, Any], package: str
) -> DiagramIR | None:
    """One module directory in full: provider icons plus reference edges."""
    groups = _module_groups(snapshot)
    group = groups.get(package)
    if not group:
        return None
    totals = _package_totals(snapshot)
    prefix = _common_package_prefix(sorted(groups))
    display = _display_package(package, prefix)
    title = str(workflow_contract.get("topic") or f"{_DETAIL_TITLE_PREFIX}{display}").strip()

    refs_in_module = {str(node.get("ref") or "") for node in group}
    uses_edges = _brief_uses_edges(snapshot)
    internal_edges = [
        edge for edge in uses_edges if edge["source_ref"] in refs_in_module and edge["target_ref"] in refs_in_module
    ]
    cross_module = [
        edge
        for edge in uses_edges
        if (edge["source_ref"] in refs_in_module) != (edge["target_ref"] in refs_in_module)
    ]
    wired = {edge["source_ref"] for edge in internal_edges} | {edge["target_ref"] for edge in internal_edges}
    ordered = _ordered_module_refs(group, wired)
    if not ordered:
        return None
    shown = ordered[:_MAX_DETAIL_CHILDREN]
    hidden_brief = len(ordered) - len(shown)
    total_blocks = totals.get(package, {}).get("class_count") or len(group)
    hidden_total = hidden_brief + max(0, total_blocks - len(group))

    container_id = "tf_mod"
    children: list[DiagramNodeIR] = []
    id_by_ref: dict[str, str] = {}
    for child_index, node in enumerate(shown):
        label, style, width, height = node_visual(node)
        cell_x = 20 + (child_index % _DETAIL_COLUMNS) * _CELL_PITCH_X + (_CELL_PITCH_X - width - 20) // 2
        cell_y = 48 + (child_index // _DETAIL_COLUMNS) * _CELL_PITCH_Y
        node_id = f"{container_id}_n{child_index + 1}"
        id_by_ref[str(node.get("ref") or "")] = node_id
        children.append(DiagramNodeIR(node_id, label, style, cell_x, cell_y, width, height, parent=container_id))
    if hidden_total:
        tail_index = len(shown)
        children.append(
            DiagramNodeIR(
                f"{container_id}_tail",
                f"+{hidden_total} more blocks",
                _TAIL_STYLE,
                20 + (tail_index % _DETAIL_COLUMNS) * _CELL_PITCH_X,
                48 + (tail_index // _DETAIL_COLUMNS) * _CELL_PITCH_Y,
                BOX_WIDTH,
                36,
                parent=container_id,
            )
        )
    child_count = len(children)
    rows = (child_count + _DETAIL_COLUMNS - 1) // _DETAIL_COLUMNS
    container_width = 40 + _DETAIL_COLUMNS * _CELL_PITCH_X
    container_height = 48 + rows * _CELL_PITCH_Y + 8
    nodes: list[DiagramNodeIR] = [
        # Container first, children after: mxGraph resolves parents in order.
        DiagramNodeIR(container_id, display, _CONTAINER_STYLE, 60, 90, container_width, container_height),
        *children,
    ]
    edges = tuple(
        DiagramEdgeIR(
            f"tf_mod_e{index + 1}",
            id_by_ref[edge["source_ref"]],
            id_by_ref[edge["target_ref"]],
            label="uses",
            style=_EDGE_STYLE,
        )
        for index, edge in enumerate(
            sorted(internal_edges, key=lambda item: (item["source_ref"], item["target_ref"]))
        )
        if edge["source_ref"] in id_by_ref and edge["target_ref"] in id_by_ref
    )
    legend_lines = [
        f"Module {display}: showing {len(shown)} of {total_blocks} blocks"
        + (f" (+{hidden_total} summarized in the tail)" if hidden_total else ""),
        f"Internal reference edges: {len(edges)}; cross-module references: {len(cross_module)} "
        "(see the module overview)",
        "Variables and outputs are counted in the overview; edges are literal references",
    ]
    if prefix:
        legend_lines.append(f"Module root: {prefix}")
    nodes.append(
        DiagramNodeIR(
            "tf_mod_legend",
            "\n".join(legend_lines),
            _LEGEND_STYLE,
            60,
            90 + container_height + 24,
            container_width,
            24 + len(legend_lines) * 14,
        )
    )
    return DiagramIR(title=title, renderer="node_link", notation="component", nodes=tuple(nodes), edges=edges)


def terraform_detail_packages(snapshot: dict[str, Any]) -> list[str]:
    """Top module directories by rendered block count (substance threshold)."""
    groups = _module_groups(snapshot)
    candidates = [
        (package, len([node for node in group if str(node.get("type") or "") in _RENDERED_KINDS]))
        for package, group in groups.items()
    ]
    substantial = [item for item in candidates if item[1] >= _DETAIL_MIN_BLOCKS]
    substantial.sort(key=lambda item: (-item[1], item[0]))
    return [package for package, _count in substantial[:_MAX_DETAIL_DIAGRAMS]]


def build_terraform_diagram_tool_calls(
    workflow_contract: dict[str, Any],
    snapshot: dict[str, Any],
    allowed_tool_names: set[str] | None,
) -> list[dict[str, Any]]:
    """Deterministic Terraform diagram set: module overview first, then the
    top-module details (quality gate on every exit; the enforcement layer
    walks the titles like the AWS detail set)."""
    from ..turn_tool_history import _build_tool_call
    from .aws_diagram_quality_gate import apply_quality_gate
    from .renderers import render_diagram_ir

    diagrams: list[DiagramIR] = []
    overview = build_terraform_module_overview_ir(dict(workflow_contract, topic=_OVERVIEW_TITLE), snapshot)
    if overview is not None:
        diagrams.append(overview)
    for package in terraform_detail_packages(snapshot):
        detail = build_terraform_module_detail_ir(dict(workflow_contract, topic=""), snapshot, package)
        if detail is not None:
            diagrams.append(detail)
    calls: list[dict[str, Any]] = []
    for diagram in diagrams:
        calls.extend(
            _build_tool_call(
                "create_diagram",
                {"title": diagram.title, "xml": apply_quality_gate(render_diagram_ir(diagram))},
                allowed_tool_names,
            )
        )
    return calls
