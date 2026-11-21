"""Compression strategy for code_structure_snapshot results.

The snapshot's ``diagram_brief`` is the binding evidence for code-structure
diagrams (uml_class, c4_component, c4_code, data_model). Without a dedicated
strategy a large snapshot got hard-capped into an unusable stringified
preview, so the dispatch guard, the deterministic renderer, and the freehand
enforcer all lost the evidence. This strategy keeps the brief intact with
explicit bounds and raises the compact token budget accordingly.
"""

from __future__ import annotations

from typing import Any

from ..prompt_catalog import render_prompt
from .budget import COMPACT_RESULT_TOKEN_BUDGET_KEY
from .config import clamp_config_int

_DEFAULT_MAX_DIAGRAM_NODES = 240
_DEFAULT_MAX_DIAGRAM_EDGES = 400
_DEFAULT_MAX_WARNINGS = 20
_DEFAULT_MAX_MEMBERS_PER_NODE = 8
_DEFAULT_COMPACT_TOKEN_BUDGET = 24000
_MAX_COMPACT_TOKEN_BUDGET = 50000
_MAX_MEMBER_CHARS = 120
_MAX_ATTRIBUTE_CHARS = 200
_MEMBER_LIST_ATTRIBUTE_KEYS = {"fields", "methods", "inline_steps"}
# An ordered pipeline attribute (a parser's ordered steps) is kept up to 24 steps per project through compression and
# roll the remainder into the explicit truncation counter the renderer reads.
_MAX_PIPELINE_STEPS_KEPT = 24
_MAX_PIPELINE_STEP_CHARS = 170
_MAX_TERRAFORM_FIELD_KEYS = 4


def _bounded_list(value: Any, limit: int) -> tuple[list[Any], int]:
    items = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    if len(items) <= limit:
        return items, 0
    return items[:limit], len(items) - limit


def _bounded_member_list(value: Any, limit: int) -> list[str]:
    items = [str(item)[:_MAX_MEMBER_CHARS] for item in value] if isinstance(value, list) else []
    if len(items) <= limit:
        return items
    hidden = len(items) - limit
    return [*items[:limit], f"+{hidden} more"]


def _bounded_node(node: dict[str, Any], *, max_members: int) -> dict[str, Any]:
    compact_node = {key: value for key, value in node.items() if key != "attributes"}
    attributes = node.get("attributes")
    if isinstance(attributes, dict):
        compact_attributes: dict[str, Any] = {}
        for key, value in attributes.items():
            if key == "pipeline_steps":
                steps = [str(item)[:_MAX_PIPELINE_STEP_CHARS] for item in value] if isinstance(value, list) else []
                compact_attributes[key] = steps[:_MAX_PIPELINE_STEPS_KEPT]
                hidden = max(0, len(steps) - _MAX_PIPELINE_STEPS_KEPT)
                if hidden:
                    compact_attributes["pipeline_steps_truncated"] = (
                        int(attributes.get("pipeline_steps_truncated") or 0) + hidden
                    )
            elif key == "pipeline_steps_truncated" and "pipeline_steps_truncated" in compact_attributes:
                continue  # already folded into the adjusted counter above
            elif key in _MEMBER_LIST_ATTRIBUTE_KEYS:
                compact_attributes[key] = _bounded_member_list(value, max_members)
            elif isinstance(value, str):
                compact_attributes[key] = value[:_MAX_ATTRIBUTE_CHARS]
            else:
                compact_attributes[key] = value
        compact_node["attributes"] = compact_attributes
    return compact_node


def _terraform_package_prefix(result: dict[str, Any], nodes: list[dict[str, Any]]) -> str:
    """Common dotted package prefix of a terraform snapshot (else empty).

    Workspace clones nest the repo under long directory chains
    (``var.repos.bitbucket.<project>.<repo>...``) that repeat in every ref,
    package attribute, file path, and edge endpoint — the single largest
    token cost of a full-repository brief. The prefix is stripped
    consistently across the compact result (and stated in
    ``package_prefix_stripped``), so all internal ref matching stays intact.
    """
    summary = result.get("service_summary")
    counts = summary.get("counts_by_language") if isinstance(summary, dict) else None
    if not (isinstance(counts, dict) and counts.get("terraform")):
        return ""
    packages: list[str] = []
    for node in nodes:
        if str(node.get("type") or "") == "package":
            packages.append(str(node.get("label") or ""))
    if not packages or any(not package for package in packages):
        return ""
    split = [package.split(".") for package in packages]
    prefix_parts: list[str] = []
    for parts in zip(*split, strict=False):
        if all(part == parts[0] for part in parts):
            prefix_parts.append(parts[0])
        else:
            break
    max_parts = min(len(parts) for parts in split) - 1  # keep at least one segment
    prefix_parts = prefix_parts[:max_parts] if max_parts > 0 else []
    return ".".join(prefix_parts)


def _strip_prefix(value: str, prefix: str) -> str:
    return value[len(prefix) + 1 :] if prefix and value.startswith(prefix + ".") else value


def _strip_ref_prefix(ref: str, prefix: str) -> str:
    for marker in ("class:", "package:"):
        if ref.startswith(marker):
            return marker + _strip_prefix(ref[len(marker):], prefix)
    return ref


def _strip_node_prefix(node: dict[str, Any], prefix: str, path_prefix: str) -> dict[str, Any]:
    stripped = dict(node)
    stripped["ref"] = _strip_ref_prefix(str(node.get("ref") or ""), prefix)
    if str(node.get("type") or "") == "package":
        stripped["label"] = _strip_prefix(str(node.get("label") or ""), prefix)
    attributes = node.get("attributes")
    if isinstance(attributes, dict):
        compact_attributes = dict(attributes)
        package = str(attributes.get("package") or "")
        if package:
            compact_attributes["package"] = _strip_prefix(package, prefix)
        file_path = str(attributes.get("file") or "")
        if path_prefix and file_path.startswith(path_prefix + "/"):
            compact_attributes["file"] = file_path[len(path_prefix) + 1 :]
        stripped["attributes"] = compact_attributes
    return stripped


def _compress_code_structure_snapshot(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    diagram_brief = result.get("diagram_brief")
    if not isinstance(diagram_brief, dict):
        return None

    max_nodes = clamp_config_int(
        config, "max_diagram_nodes", default=_DEFAULT_MAX_DIAGRAM_NODES, minimum=4, maximum=500
    )
    max_edges = clamp_config_int(
        config, "max_diagram_edges", default=_DEFAULT_MAX_DIAGRAM_EDGES, minimum=1, maximum=1000
    )
    max_warnings = clamp_config_int(config, "max_warnings", default=_DEFAULT_MAX_WARNINGS, minimum=1, maximum=100)
    max_members = clamp_config_int(
        config, "max_members_per_node", default=_DEFAULT_MAX_MEMBERS_PER_NODE, minimum=1, maximum=20
    )

    selected_nodes, omitted_nodes = _bounded_list(diagram_brief.get("selected_nodes"), max_nodes)
    summary = result.get("service_summary")
    counts = summary.get("counts_by_language") if isinstance(summary, dict) else None
    is_terraform = bool(isinstance(counts, dict) and counts.get("terraform"))
    if is_terraform:
        # Terraform views render from type/name/provider, not from argument
        # key lists; a short key sample keeps the evidence character while a
        # 400-block full-repo brief stays inside its token budget.
        max_members = min(max_members, _MAX_TERRAFORM_FIELD_KEYS)
    package_prefix = _terraform_package_prefix(result, selected_nodes)
    path_prefix = package_prefix.replace(".", "/")
    if package_prefix:
        selected_nodes = [_strip_node_prefix(node, package_prefix, path_prefix) for node in selected_nodes]
    selected_nodes = [_bounded_node(node, max_members=max_members) for node in selected_nodes]
    selected_edges, omitted_edges = _bounded_list(diagram_brief.get("selected_edges"), max_edges)
    if package_prefix:
        selected_edges = [
            {
                **edge,
                "source_ref": _strip_ref_prefix(str(edge.get("source_ref") or ""), package_prefix),
                "target_ref": _strip_ref_prefix(str(edge.get("target_ref") or ""), package_prefix),
            }
            for edge in selected_edges
        ]

    warnings = [str(warning)[:300] for warning in (result.get("warnings") or [])[:max_warnings]]

    compact: dict[str, Any] = {
        "workspace": result.get("workspace"),
        "generated_at": result.get("generated_at"),
        "service_summary": result.get("service_summary"),
        "scope": result.get("scope"),
        "diagram_brief": {
            "selected_nodes": selected_nodes,
            "selected_edges": selected_edges,
            "truncated": bool(diagram_brief.get("truncated") or omitted_nodes or omitted_edges),
            "omitted_node_count": omitted_nodes,
            "omitted_edge_count": omitted_edges,
        },
        "warning_count": len(result.get("warnings") or []),
        "warnings": warnings,
        **({"package_prefix_stripped": package_prefix} if package_prefix else {}),
        "compression_note": render_prompt("tool_guard.compression.code_structure.note"),
        COMPACT_RESULT_TOKEN_BUDGET_KEY: clamp_config_int(
            config,
            "compact_token_budget",
            default=_DEFAULT_COMPACT_TOKEN_BUDGET,
            minimum=3000,
            maximum=_MAX_COMPACT_TOKEN_BUDGET,
        ),
    }
    return compact


__all__ = ["_compress_code_structure_snapshot"]
