"""AWS topology snapshot diff connector tool."""

from __future__ import annotations

import json
from typing import Any

from ..context import ToolContext
from .aws_topology import build_aws_topology_snapshot
from .aws_topology_common import compact_payload

NODE_COMPARE_KEYS = ("type", "label", "service", "region", "arn", "tags", "attributes")
EDGE_COMPARE_KEYS = ("source", "target", "type", "service", "attributes")
HIGH_IMPACT_NODE_TYPES = {"eks_cluster", "rds_instance", "vpc", "subnet", "load_balancer", "waf_web_acl"}


def _snapshot_from_params(params: dict[str, Any], *names: str) -> dict[str, Any] | None:
    for name in names:
        value = params.get(name)
        if isinstance(value, dict):
            return value
    return None


def _node_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = snapshot.get("nodes")
    if not isinstance(nodes, list):
        return {}
    return {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")}


def _edge_key(edge: dict[str, Any]) -> str:
    return f"{edge.get('source')}|{edge.get('target')}|{edge.get('type')}"


def _edge_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    edges = snapshot.get("edges")
    if not isinstance(edges, list):
        return {}
    return {_edge_key(edge): edge for edge in edges if isinstance(edge, dict) and edge.get("source") and edge.get("target")}


def _stable_subset(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: compact_payload(item.get(key)) for key in keys}


def _stable_json(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    return json.dumps(_stable_subset(item, keys), sort_keys=True, separators=(",", ":"), default=str)


def _changed_fields(before: dict[str, Any], after: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    changed = []
    for key in keys:
        if _stable_json({key: before.get(key)}, (key,)) != _stable_json({key: after.get(key)}, (key,)):
            changed.append(key)
    return changed


def _node_severity(change_type: str, node: dict[str, Any]) -> str:
    node_type = str(node.get("type") or "")
    if node_type in HIGH_IMPACT_NODE_TYPES:
        return "high" if change_type == "removed" else "medium"
    if node_type in {"security_group", "cidr"}:
        return "medium"
    return "low"


def _edge_severity(change_type: str, edge: dict[str, Any]) -> str:
    edge_type = str(edge.get("type") or "")
    if edge_type in {"allows_ingress", "routes_to", "uses_security_group"}:
        return "medium" if change_type == "changed" else "high"
    return "low"


def _service_of(item: dict[str, Any]) -> str:
    return str(item.get("service") or "unknown")


def _node_diff(change_type: str, item: dict[str, Any], *, before: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "change_type": change_type,
        "id": item.get("id"),
        "type": item.get("type"),
        "label": item.get("label"),
        "service": _service_of(item),
        "severity": _node_severity(change_type, item),
        "after": _stable_subset(item, NODE_COMPARE_KEYS),
        "before": _stable_subset(before or {}, NODE_COMPARE_KEYS) if before else None,
        "changed_fields": _changed_fields(before or {}, item, NODE_COMPARE_KEYS) if before else [],
        "evidence": {
            "before": list((before or {}).get("evidence") or []),
            "after": list(item.get("evidence") or []),
        },
    }
    return payload


def _edge_diff(change_type: str, item: dict[str, Any], *, before: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "change_type": change_type,
        "key": _edge_key(item),
        "source": item.get("source"),
        "target": item.get("target"),
        "type": item.get("type"),
        "service": _service_of(item),
        "severity": _edge_severity(change_type, item),
        "after": _stable_subset(item, EDGE_COMPARE_KEYS),
        "before": _stable_subset(before or {}, EDGE_COMPARE_KEYS) if before else None,
        "changed_fields": _changed_fields(before or {}, item, EDGE_COMPARE_KEYS) if before else [],
        "evidence": {
            "before": list((before or {}).get("evidence") or []),
            "after": list(item.get("evidence") or []),
        },
    }
    return payload


def _scope_warnings(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    warnings = []
    for key in ("account_id", "region"):
        if baseline.get(key) and candidate.get(key) and baseline.get(key) != candidate.get(key):
            warnings.append(
                {
                    "severity": "warning",
                    "reason": f"{key}_mismatch",
                    "message": f"Baseline {key} differs from candidate {key}; diff may not be directly comparable.",
                }
            )

    baseline_scope = baseline.get("scope") if isinstance(baseline.get("scope"), dict) else {}
    candidate_scope = candidate.get("scope") if isinstance(candidate.get("scope"), dict) else {}
    baseline_services = set(baseline_scope.get("services_succeeded") or [])
    candidate_services = set(candidate_scope.get("services_succeeded") or [])
    if baseline_services and candidate_services and baseline_services != candidate_services:
        warnings.append(
            {
                "severity": "warning",
                "reason": "service_coverage_mismatch",
                "message": "Baseline and candidate snapshots have different successful service coverage.",
                "baseline_only": sorted(baseline_services - candidate_services),
                "candidate_only": sorted(candidate_services - baseline_services),
            }
        )
    return warnings


def _service_summary(node_diffs: list[dict[str, Any]], edge_diffs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for diff in [*node_diffs, *edge_diffs]:
        service = str(diff.get("service") or "unknown")
        change_type = str(diff.get("change_type") or "changed")
        service_counts = summary.setdefault(service, {"added": 0, "removed": 0, "changed": 0})
        service_counts[change_type] = service_counts.get(change_type, 0) + 1
    return summary


def compare_aws_topology_snapshots(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_nodes = _node_map(baseline)
    candidate_nodes = _node_map(candidate)
    baseline_edges = _edge_map(baseline)
    candidate_edges = _edge_map(candidate)

    node_diffs = []
    for item_id in sorted(candidate_nodes.keys() - baseline_nodes.keys()):
        node_diffs.append(_node_diff("added", candidate_nodes[item_id]))
    for item_id in sorted(baseline_nodes.keys() - candidate_nodes.keys()):
        node_diffs.append(_node_diff("removed", baseline_nodes[item_id]))
    for item_id in sorted(baseline_nodes.keys() & candidate_nodes.keys()):
        before = baseline_nodes[item_id]
        after = candidate_nodes[item_id]
        if _stable_json(before, NODE_COMPARE_KEYS) != _stable_json(after, NODE_COMPARE_KEYS):
            node_diffs.append(_node_diff("changed", after, before=before))

    edge_diffs = []
    for item_id in sorted(candidate_edges.keys() - baseline_edges.keys()):
        edge_diffs.append(_edge_diff("added", candidate_edges[item_id]))
    for item_id in sorted(baseline_edges.keys() - candidate_edges.keys()):
        edge_diffs.append(_edge_diff("removed", baseline_edges[item_id]))
    for item_id in sorted(baseline_edges.keys() & candidate_edges.keys()):
        before = baseline_edges[item_id]
        after = candidate_edges[item_id]
        if _stable_json(before, EDGE_COMPARE_KEYS) != _stable_json(after, EDGE_COMPARE_KEYS):
            edge_diffs.append(_edge_diff("changed", after, before=before))

    return {
        "status": "ok",
        "baseline": _snapshot_metadata(baseline),
        "candidate": _snapshot_metadata(candidate),
        "summary": {
            "nodes_added": sum(1 for diff in node_diffs if diff["change_type"] == "added"),
            "nodes_removed": sum(1 for diff in node_diffs if diff["change_type"] == "removed"),
            "nodes_changed": sum(1 for diff in node_diffs if diff["change_type"] == "changed"),
            "edges_added": sum(1 for diff in edge_diffs if diff["change_type"] == "added"),
            "edges_removed": sum(1 for diff in edge_diffs if diff["change_type"] == "removed"),
            "edges_changed": sum(1 for diff in edge_diffs if diff["change_type"] == "changed"),
        },
        "service_summary": _service_summary(node_diffs, edge_diffs),
        "node_diffs": node_diffs,
        "edge_diffs": edge_diffs,
        "warnings": _scope_warnings(baseline, candidate),
    }


def _snapshot_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    nodes = snapshot.get("nodes") if isinstance(snapshot.get("nodes"), list) else []
    edges = snapshot.get("edges") if isinstance(snapshot.get("edges"), list) else []
    return {
        "account_id": snapshot.get("account_id"),
        "region": snapshot.get("region"),
        "generated_at": snapshot.get("generated_at"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "scope": snapshot.get("scope") if isinstance(snapshot.get("scope"), dict) else {},
    }


class AwsTopologyDiffTool:
    name = "aws_topology_diff"
    description = (
        "Compare two AWS topology snapshots and report added, removed and changed nodes and edges with severity, "
        "service grouping and source evidence."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        params = params or {}
        baseline = _snapshot_from_params(params, "baseline_snapshot", "before_snapshot")
        candidate = _snapshot_from_params(params, "candidate_snapshot", "after_snapshot", "current_snapshot")
        if baseline is None:
            return {"status": "invalid_input", "error": "baseline_snapshot is required"}
        if candidate is None:
            snapshot_params = params.get("snapshot_params") if isinstance(params.get("snapshot_params"), dict) else {}
            candidate = await build_aws_topology_snapshot(context, snapshot_params)
        return compare_aws_topology_snapshots(baseline, candidate)
