"""Focused detail-diagram candidates derived from an AWS topology snapshot."""

from __future__ import annotations

from typing import Any

from .aws_cell_text import _safe_cell_id

_DETAIL_CANDIDATE_DEFINITIONS = {
    "network": {
        "title": "Network and routing detail",
        "reason": "VPC, subnet, gateway, and route-table structure is present.",
        "node_types": {
            "vpc",
            "subnet",
            "internet_gateway",
            "nat_gateway",
            "route_table",
            "cidr",
            "vpc_endpoint",
            "vpc_peering",
            "transit_gateway",
        },
        # placement edges (attached_to/runs_in/uses_subnet) are required so
        # gateways and endpoints nest into their VPC/subnet tiers instead of
        # falling into the regional box with empty tier containers.
        "edge_types": {
            "belongs_to",
            "routes_to",
            "uses_route_table",
            "attached_to",
            "runs_in",
            "uses_subnet",
        },
    },
    "ingress": {
        "title": "Ingress and load balancing detail",
        "reason": "Ingress-facing WAF, load balancer, or target-group resources are present.",
        "node_types": {"waf_web_acl", "load_balancer", "target_group", "cloudfront_distribution", "route53_zone"},
        "edge_types": {"protects", "routes_to", "targets", "resolves_to"},
    },
    "compute": {
        "title": "Compute platform detail",
        "reason": "EKS, nodegroup, autoscaling, or Lambda resources are present.",
        "node_types": {"eks_cluster", "eks_nodegroup", "autoscaling_group", "lambda_function"},
        "edge_types": {"runs_in", "manages", "belongs_to", "uses_security_group", "triggers"},
    },
    "data": {
        "title": "Data services detail",
        "reason": "Database, table, or bucket resources are present.",
        "node_types": {
            "rds_instance",
            "rds_cluster",
            "rds_proxy",
            "dynamodb_table",
            "s3_bucket",
            "elasticache_cluster",
            "efs_file_system",
        },
        "edge_types": {
            "uses_security_group",
            "allows_ingress_to",
            "allows_egress_to",
            "belongs_to",
            "triggers",
            "delivers_to",
        },
    },
    "security": {
        "title": "Security group and traffic detail",
        "reason": "Security groups, CIDR peers, or explicit ingress/egress rules are present.",
        "node_types": {"security_group", "cidr"},
        "edge_types": {"uses_security_group", "allows_ingress_to", "allows_egress_to"},
    },
    "ci_cd": {
        "title": "CI/CD pipeline detail",
        "reason": "CodePipeline resources are present.",
        "node_types": {"codepipeline"},
        "edge_types": {"belongs_to"},
    },
}


def build_aws_topology_detail_candidates(topology_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    selected_nodes, selected_edges, _brief = _topology_brief_parts(topology_result)
    if not selected_nodes:
        return []

    node_types = {str(node.get("type") or "").strip() for node in selected_nodes if str(node.get("type") or "").strip()}
    edge_types = {str(edge.get("type") or "").strip() for edge in selected_edges if str(edge.get("type") or "").strip()}
    candidates: list[dict[str, Any]] = []
    for candidate_id, definition in _DETAIL_CANDIDATE_DEFINITIONS.items():
        candidate_node_types = set(definition["node_types"]) & node_types
        candidate_edge_types = set(definition["edge_types"]) & edge_types
        if not candidate_node_types and not candidate_edge_types:
            continue
        estimated_nodes = sum(
            1 for node in selected_nodes if str(node.get("type") or "").strip() in definition["node_types"]
        )
        estimated_edges = sum(
            1 for edge in selected_edges if str(edge.get("type") or "").strip() in definition["edge_types"]
        )
        candidates.append(
            {
                "id": candidate_id,
                "title": definition["title"],
                "reason": definition["reason"],
                "node_types": sorted(candidate_node_types),
                "edge_types": sorted(candidate_edge_types),
                "estimated_nodes": estimated_nodes,
                "estimated_edges": estimated_edges,
            }
        )
    candidates.extend(_application_detail_candidates(selected_nodes, selected_edges))
    return candidates


_APP_DETAIL_EDGE_TYPES = {"routes_to", "protects", "targets", "uses_security_group"}
_MAX_APP_CANDIDATES = 3


def _application_detail_candidates(
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from .aws_diagram_naming import normalize_label

    ref_types: dict[str, str] = {}
    lb_refs_by_app: dict[str, list[str]] = {}
    for node in selected_nodes:
        ref = str(node.get("ref") or node.get("id") or "").strip()
        node_type = str(node.get("type") or "").strip()
        if ref:
            ref_types[ref] = node_type
        if node_type == "load_balancer" and ref:
            app = normalize_label(str(node.get("label") or ""), "load_balancer")
            lb_refs_by_app.setdefault(app, []).append(ref)

    candidates: list[dict[str, Any]] = []
    for app, lb_refs in sorted(lb_refs_by_app.items()):
        refs = set(lb_refs)
        edge_count = 0
        for edge in selected_edges:
            if str(edge.get("type") or "").strip() not in _APP_DETAIL_EDGE_TYPES:
                continue
            source = str(edge.get("source_ref") or edge.get("source") or "").strip()
            target = str(edge.get("target_ref") or edge.get("target") or "").strip()
            if source in lb_refs or target in lb_refs:
                edge_count += 1
                refs.update(ref for ref in (source, target) if ref)
        candidates.append(
            {
                "id": f"app_{_safe_cell_id(app, fallback='app')}",
                "title": f"Application detail - {app}",
                "reason": f"Load balancer '{app}' with its target groups and security wiring.",
                "node_types": sorted({ref_types.get(ref, "") for ref in refs} - {""}),
                "edge_types": sorted(_APP_DETAIL_EDGE_TYPES),
                "node_refs": sorted(refs),
                "estimated_nodes": len(refs),
                "estimated_edges": edge_count,
            }
        )
    candidates.sort(key=lambda candidate: (-candidate["estimated_edges"], candidate["id"]))
    return candidates[:_MAX_APP_CANDIDATES]


# A detail diagram is only worth a page when the candidate has substance;
# below these thresholds the overview already tells the whole story.
# Application candidates pin a deliberately small exact node set, so they get
# their own lower bar.
_DETAIL_MIN_NODES = 6
_DETAIL_MIN_EDGES = 8
_APP_DETAIL_MIN_NODES = 3
_APP_DETAIL_MIN_EDGES = 2


def _rank_detail_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _score(candidate: dict[str, Any]) -> tuple[int, int, int]:
        return (
            int(candidate.get("estimated_edges") or 0) * 3
            + int(candidate.get("estimated_nodes") or 0),
            int(candidate.get("estimated_edges") or 0),
            int(candidate.get("estimated_nodes") or 0),
        )

    return sorted(candidates, key=_score, reverse=True)


def _substantial_detail_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    substantial: list[dict[str, Any]] = []
    for candidate in candidates:
        nodes = int(candidate.get("estimated_nodes") or 0)
        edges = int(candidate.get("estimated_edges") or 0)
        if str(candidate.get("id") or "").startswith("app_"):
            if nodes >= _APP_DETAIL_MIN_NODES and edges >= _APP_DETAIL_MIN_EDGES:
                substantial.append(candidate)
        elif nodes >= _DETAIL_MIN_NODES or edges >= _DETAIL_MIN_EDGES:
            substantial.append(candidate)
    return substantial


def _select_detail_candidate_graph(
    candidate: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_node_types = {str(item).strip() for item in candidate.get("node_types") or [] if str(item).strip()}
    candidate_edge_types = {str(item).strip() for item in candidate.get("edge_types") or [] if str(item).strip()}
    node_by_ref = {str(node.get("ref") or node.get("id") or "").strip(): node for node in selected_nodes}
    explicit_refs = {str(ref).strip() for ref in candidate.get("node_refs") or [] if str(ref).strip()}
    if explicit_refs:
        # Application candidates pin an exact node set; type-based expansion
        # would pull in every load balancer/target group in the account.
        primary_refs = {ref for ref in explicit_refs if ref in node_by_ref}
    else:
        primary_refs = {
            ref
            for ref, node in node_by_ref.items()
            if ref and str(node.get("type") or "").strip() in candidate_node_types
        }
    detail_edges: list[dict[str, Any]] = []
    detail_refs = set(primary_refs)
    for edge in selected_edges:
        edge_type = str(edge.get("type") or "").strip()
        if edge_type not in candidate_edge_types:
            continue
        source_ref = str(edge.get("source_ref") or edge.get("source") or "").strip()
        target_ref = str(edge.get("target_ref") or edge.get("target") or "").strip()
        if source_ref not in primary_refs and target_ref not in primary_refs:
            continue
        detail_edges.append(edge)
        if source_ref:
            detail_refs.add(source_ref)
        if target_ref:
            detail_refs.add(target_ref)
    detail_nodes = [node for ref, node in node_by_ref.items() if ref in detail_refs]
    return detail_nodes, detail_edges



def _topology_brief_parts(
    topology_result: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(topology_result, dict):
        return [], [], {}
    brief = topology_result.get("diagram_brief")
    if not isinstance(brief, dict):
        brief = {}
    selected_nodes = [
        node for node in (brief.get("selected_nodes") or topology_result.get("nodes") or []) if isinstance(node, dict)
    ]
    selected_edges = [
        edge for edge in (brief.get("selected_edges") or topology_result.get("edges") or []) if isinstance(edge, dict)
    ]
    return selected_nodes, selected_edges, brief
