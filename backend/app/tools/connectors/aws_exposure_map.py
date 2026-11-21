"""AWS public exposure map connector tool."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_topology import build_aws_topology_snapshot

PUBLIC_CIDRS = {"0.0.0.0/0", "::/0"}
PUBLIC_ENDPOINT_NODE_TYPES = {"load_balancer", "eks_cluster", "rds_instance"}


def _nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("nodes")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _edges(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("edges")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _node_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in _nodes(snapshot) if item.get("id")}


def _is_public_endpoint(node: dict[str, Any]) -> tuple[bool, str | None]:
    attrs = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
    if node.get("type") == "load_balancer" and attrs.get("scheme") == "internet-facing":
        return True, "internet_facing_load_balancer"
    if node.get("type") == "eks_cluster" and attrs.get("endpoint_public_access") is True:
        return True, "public_eks_endpoint"
    if node.get("type") == "rds_instance" and attrs.get("publicly_accessible") is True:
        return True, "public_rds_instance"
    return False, None


def _public_ingress_edges(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = _node_map(snapshot)
    exposure_edges = []
    for edge in _edges(snapshot):
        if edge.get("type") != "allows_ingress_to":
            continue
        source = nodes.get(str(edge.get("source"))) or {}
        if source.get("label") not in PUBLIC_CIDRS:
            continue
        exposure_edges.append(
            {
                "source": edge.get("source"),
                "target": edge.get("target"),
                "type": "public_ingress",
                "service": edge.get("service"),
                "attributes": edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {},
                "evidence": list(edge.get("evidence") or []),
            }
        )
    return exposure_edges


def _exposed_nodes(snapshot: dict[str, Any], exposure_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes = _node_map(snapshot)
    exposed_ids = {str(edge.get("target")) for edge in exposure_edges if edge.get("target")}
    items = []
    for node in _nodes(snapshot):
        public_endpoint, reason = _is_public_endpoint(node)
        if node.get("id") not in exposed_ids and not public_endpoint:
            continue
        exposure_reasons = []
        if node.get("id") in exposed_ids:
            exposure_reasons.append("public_ingress_rule")
        if reason:
            exposure_reasons.append(reason)
        items.append(
            {
                "node_id": node.get("id"),
                "type": node.get("type"),
                "label": node.get("label"),
                "service": node.get("service"),
                "severity": "high" if "public_ingress_rule" in exposure_reasons else "medium",
                "exposure_reasons": exposure_reasons,
                "attributes": node.get("attributes") if isinstance(node.get("attributes"), dict) else {},
                "evidence": list(node.get("evidence") or []),
            }
        )

    missing_targets = exposed_ids - set(nodes)
    for node_id in sorted(missing_targets):
        items.append(
            {
                "node_id": node_id,
                "type": "unknown",
                "label": node_id,
                "service": "unknown",
                "severity": "medium",
                "exposure_reasons": ["public_ingress_rule_without_target_node"],
                "attributes": {},
                "evidence": [],
            }
        )
    return items


def _public_sources(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": node.get("id"),
            "label": node.get("label"),
            "type": node.get("type"),
            "evidence": list(node.get("evidence") or []),
        }
        for node in _nodes(snapshot)
        if node.get("label") in PUBLIC_CIDRS
    ]


async def build_aws_exposure_map(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    topology = params.get("topology_snapshot") if isinstance(params.get("topology_snapshot"), dict) else None
    topology_source = "provided" if topology else "collected"
    if topology is None:
        snapshot_params = params.get("snapshot_params") if isinstance(params.get("snapshot_params"), dict) else {}
        topology = await build_aws_topology_snapshot(context, snapshot_params)

    exposure_edges = _public_ingress_edges(topology)
    exposed_nodes = _exposed_nodes(topology, exposure_edges)
    return {
        "status": "ok",
        "topology_source": topology_source,
        "account_id": topology.get("account_id"),
        "region": topology.get("region"),
        "summary": {
            "public_source_count": len(_public_sources(topology)),
            "exposed_node_count": len(exposed_nodes),
            "public_ingress_edge_count": len(exposure_edges),
            "high_severity_count": sum(1 for item in exposed_nodes if item.get("severity") == "high"),
        },
        "public_sources": _public_sources(topology),
        "exposed_nodes": exposed_nodes,
        "exposure_edges": exposure_edges,
        "warnings": list(topology.get("warnings") or []),
    }


class AwsExposureMapTool:
    name = "aws_exposure_map"
    description = (
        "Build a visualizable AWS public exposure map from topology evidence, including public ingress rules and "
        "internet-facing runtime nodes."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_aws_exposure_map(context, params or {})
