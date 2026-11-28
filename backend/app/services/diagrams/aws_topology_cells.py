"""Title, legend and node-label cells for AWS topology diagrams."""

from __future__ import annotations

from typing import Any

from .aws_cell_text import _safe_cell_id, _truncate_label, _xml_value
from .aws_topology_shapes import _service_label, _service_rank


def _title_cell(title: str, topology_result: dict[str, Any]) -> str:
    summary = topology_result.get("service_summary") if isinstance(topology_result, dict) else {}
    account_id = str(topology_result.get("account_id") or (summary or {}).get("account_id") or "").strip()
    region = str(topology_result.get("region") or (summary or {}).get("region") or "").strip()
    resource_count = str((summary or {}).get("resource_node_count") or "").strip()
    edge_count = str((summary or {}).get("edge_count") or "").strip()
    subtitle_parts = [part for part in (account_id, region) if part]
    if resource_count or edge_count:
        subtitle_parts.append(f"{resource_count or '?'} resources / {edge_count or '?'} relationships")
    value = _xml_value(title)
    if subtitle_parts:
        value = f"{value}&#xa;{_xml_value(' | '.join(subtitle_parts))}"
    return (
        f'<mxCell id="topology_title" value="{value}" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;'
        'whiteSpace=wrap;fontSize=22;fontStyle=1;fontColor=#111827;" vertex="1" parent="1">'
        '<mxGeometry x="60" y="24" width="940" height="58" as="geometry"/></mxCell>'
    )


def _legend_cell(
    topology_result: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
    *,
    omitted_edge_count: int = 0,
) -> str:
    coverage = {}
    brief = topology_result.get("diagram_brief") if isinstance(topology_result, dict) else {}
    if isinstance(brief, dict):
        service_coverage = brief.get("service_coverage")
        if isinstance(service_coverage, dict):
            coverage = service_coverage.get("selected_node_counts_by_service") or {}
    if not isinstance(coverage, dict) or not coverage:
        coverage = {}
        for node in selected_nodes:
            service = str(node.get("service") or "unknown")
            coverage[service] = int(coverage.get(service, 0)) + 1
    services = ", ".join(f"{_service_label(service)} {count}" for service, count in _sorted_service_counts(coverage))
    value = (
        "Evidence-backed draw.io topology from aws_topology_snapshot.diagram_brief.selected_nodes and selected_edges. "
        f"Rendered nodes: {len(selected_nodes)}. Rendered relationships: {len(selected_edges)}."
    )
    if services:
        value = f"{value} Services: {services}."
    aggregation = topology_result.get("_overview_aggregation") if isinstance(topology_result, dict) else {}
    if isinstance(aggregation, dict) and aggregation.get("aggregated_node_count"):
        value = (
            f"{value} Overview aggregation summarized {aggregation.get('aggregated_node_count')} high-cardinality "
            f"resources into {aggregation.get('original_node_count')} to {aggregation.get('rendered_node_count')} "
            "rendered nodes; full detail remains in the topology artifact."
        )
    if omitted_edge_count > 0:
        value = (
            f"{value} Account ownership is shown in title metadata; "
            f"{omitted_edge_count} account-ownership relationships were omitted from the canvas."
        )
    coverage_gap = _coverage_gap_note(topology_result)
    if coverage_gap:
        value = f"{value} {coverage_gap}"
    return (
        f'<mxCell id="topology_legend" value="{_xml_value(value)}" '
        'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8fafc;strokeColor=#cbd5e1;'
        'fontSize=12;fontColor=#334155;align=left;verticalAlign=top;spacing=10;" vertex="1" parent="1">'
        '<mxGeometry x="60" y="92" width="1480" height="64" as="geometry"/></mxCell>'
    )


def _coverage_gap_note(topology_result: dict[str, Any]) -> str:
    if not isinstance(topology_result, dict):
        return ""
    summary = topology_result.get("service_summary")
    scope = topology_result.get("scope")
    summary = summary if isinstance(summary, dict) else {}
    scope = scope if isinstance(scope, dict) else {}

    def _names(key: str) -> list[str]:
        values = summary.get(key) or scope.get(key) or []
        return sorted({str(item).strip() for item in values if str(item).strip()})

    parts: list[str] = []
    partial = set(_names("services_partial"))
    failed = [name for name in _names("services_failed") if name not in partial]
    if failed:
        parts.append(
            f"Not readable in this account (permissions/errors): {', '.join(failed)}."
        )
    if partial:
        parts.append(
            "Partially readable (failed in at least one region): "
            f"{', '.join(sorted(partial))}."
        )
    skipped = _names("services_skipped")
    if skipped:
        parts.append(f"Excluded by project policy: {', '.join(skipped)}.")
    return " ".join(parts)


def _sorted_service_counts(coverage: dict[str, Any]) -> list[tuple[str, int]]:
    counts = []
    for service, count in coverage.items():
        try:
            counts.append((str(service), int(count)))
        except (TypeError, ValueError):
            continue
    return sorted(counts, key=lambda item: (_service_rank(item[0]), item[0]))



def _node_value(
    label: str,
    node_type: str,
    node: dict[str, Any],
    *,
    label_max: int = 44,
    subtitle_max: int = 54,
) -> str:
    attrs = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
    subtitle = _node_subtitle(node_type, attrs)
    return f"{_xml_value(_truncate_label(label, label_max))}&#xa;{_xml_value(_truncate_label(subtitle, subtitle_max))}"


# Summary subtitles for aggregated nodes whose type has a fixed plural label.
_SUMMARY_SUBTITLES = {
    "s3_bucket": "S3 buckets",
    "codepipeline": "CodePipeline",
    "security_group": "Security groups",
    "cidr": "CIDR sources",
}


def _node_subtitle(node_type: str, attrs: dict[str, Any]) -> str:
    subtitle = node_type.replace("_", " ")
    if node_type == "subnet":
        tier = str(attrs.get("subnet_tier") or "").strip()
        az = str(attrs.get("availability_zone") or "").strip()
        prefix = f"{tier.title()} subnet" if tier else "Subnet"
        subtitle = " / ".join(part for part in (prefix, az) if part)
    elif node_type == "eks_nodegroup":
        subtitle = _eks_nodegroup_subtitle(attrs)
    elif node_type == "eks_cluster" and attrs.get("folded_nodegroups"):
        subtitle = _eks_cluster_subtitle(attrs)
    elif node_type == "load_balancer" and (attrs.get("absorbed_target_groups") or attrs.get("listeners")):
        subtitle = _load_balancer_subtitle(attrs)
    elif node_type == "target_group" and attrs.get("summary_count"):
        subtitle = "no LB route in evidence"
    elif node_type == "route_table" and attrs.get("summary_count"):
        subtitle = "no default route in evidence"
    elif node_type == "dynamodb_table":
        subtitle = _dynamodb_table_subtitle(attrs)
    elif node_type in _SUMMARY_SUBTITLES and attrs.get("summary_count"):
        subtitle = f"{_SUMMARY_SUBTITLES[node_type]} / summarized {attrs.get('summary_count')}"
    elif node_type in {"internet_gateway", "nat_gateway", "route_table"}:
        subtitle = node_type.replace("_", " ").title()
    return subtitle


def _eks_nodegroup_subtitle(attrs: dict[str, Any]) -> str:
    status = str(attrs.get("status") or "").strip()
    desired = attrs.get("desired_size")
    subtitle = "EKS nodegroup"
    if status or desired is not None:
        subtitle = f"nodegroup / {status or '?'} / {desired if desired is not None else '?'} nodes"
    if attrs.get("asg_backed"):
        subtitle = f"{subtitle} / ASG"
    return subtitle


def _eks_cluster_subtitle(attrs: dict[str, Any]) -> str:
    count = attrs.get("folded_nodegroups")
    node_total = attrs.get("folded_node_total")
    subtitle = f"EKS cluster / {count} nodegroups"
    if node_total:
        subtitle = f"{subtitle} / {node_total} nodes"
    return subtitle


def _load_balancer_subtitle(attrs: dict[str, Any]) -> str:
    parts = [str(attrs.get("scheme") or "").strip() or "load balancer"]
    listeners = [str(item) for item in (attrs.get("listeners") or []) if str(item)]
    if listeners:
        parts.append(" ".join(listeners[:3]))
    count = attrs.get("absorbed_target_groups")
    if count:
        parts.append(f"{count} {'target group' if count == 1 else 'target groups'}")
    return " / ".join(parts)


def _dynamodb_table_subtitle(attrs: dict[str, Any]) -> str:
    status = str(attrs.get("status") or "").strip()
    billing = str(attrs.get("billing_mode") or "").strip()
    summary_count = attrs.get("summary_count")
    if summary_count:
        return f"DynamoDB tables / summarized {summary_count}"
    return " / ".join(part for part in ("DynamoDB table", status, billing) if part)


def _node_refs(nodes: list[dict[str, Any]]) -> dict[int, str]:
    refs: dict[int, str] = {}
    used = {"topology_title", "topology_legend", "aws_cloud", "regional_services"}
    for index, node in enumerate(nodes, start=1):
        candidate = str(node.get("ref") or "").strip() or f"n{index}"
        candidate = _safe_cell_id(candidate, fallback=f"n{index}")
        if candidate in used:
            candidate = f"n{index}"
        while candidate in used:
            candidate = f"{candidate}_{index}"
        used.add(candidate)
        refs[id(node)] = candidate
    return refs

