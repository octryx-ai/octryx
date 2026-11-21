"""Aggregation of high-cardinality resource types for large AWS overview diagrams."""

from __future__ import annotations

from typing import Any

from .aws_cell_text import _safe_cell_id
from .aws_topology_edges import _edge_value

_LARGE_OVERVIEW_NODE_THRESHOLD = 120
_AGGREGATE_TYPE_LIMITS = {
    "cidr": 6,
    "security_group": 16,
    "dynamodb_table": 12,
    "s3_bucket": 8,
    "codepipeline": 6,
    # high-cardinality extended services collapse to one summary node each so
    # "read everything" does not flood the regional group
    "ecr_repository": 6,
    "sqs_queue": 6,
    "sns_topic": 6,
    "secrets_manager_secret": 6,
    "lambda_function": 8,
    "step_function": 6,
    "eventbridge_bus": 4,
}
_STRUCTURAL_NODE_TYPES = {
    "aws_account",
    "vpc",
    "subnet",
    "internet_gateway",
    "nat_gateway",
    "route_table",
    "load_balancer",
    "target_group",
    "eks_cluster",
    "eks_nodegroup",
    "autoscaling_group",
    "rds_instance",
    "lambda_function",
    "waf_web_acl",
}


def _shape_large_overview_selection(
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
    brief: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if str(brief.get("mode") or "") != "full" or len(selected_nodes) <= _LARGE_OVERVIEW_NODE_THRESHOLD:
        return selected_nodes, selected_edges, {}

    type_counts: dict[str, int] = {}
    for node in selected_nodes:
        node_type = str(node.get("type") or "")
        type_counts[node_type] = type_counts.get(node_type, 0) + 1

    used_security_group_refs = {
        str(edge.get("target_ref") or edge.get("target") or "").strip()
        for edge in selected_edges
        if str(edge.get("type") or "") == "uses_security_group"
    }
    aggregate_nodes: dict[tuple[str, str], dict[str, Any]] = {}
    aggregate_counts: dict[tuple[str, str], int] = {}
    ref_replacements: dict[str, str] = {}
    shaped_nodes: list[dict[str, Any]] = []

    for node in selected_nodes:
        aggregate_key = _aggregate_key_for_overview_node(node, type_counts, used_security_group_refs)
        node_ref = str(node.get("ref") or node.get("id") or "").strip()
        if not aggregate_key or not node_ref:
            shaped_nodes.append(node)
            continue
        aggregate_ref = _aggregate_ref(aggregate_key)
        ref_replacements[node_ref] = aggregate_ref
        aggregate_counts[aggregate_key] = aggregate_counts.get(aggregate_key, 0) + 1
        if aggregate_key not in aggregate_nodes:
            service, node_type = aggregate_key
            aggregate_nodes[aggregate_key] = {
                "ref": aggregate_ref,
                "type": node_type,
                "label": _aggregate_label(node_type, 0),
                "service": service,
                "region": node.get("region"),
                "attributes": {"summary_count": 0, "summary_type": node_type},
            }

    for aggregate_key, count in aggregate_counts.items():
        aggregate_node = aggregate_nodes[aggregate_key]
        aggregate_node["label"] = _aggregate_label(aggregate_key[1], count)
        aggregate_node["attributes"] = {
            **dict(aggregate_node.get("attributes") or {}),
            "summary_count": count,
        }
        shaped_nodes.append(aggregate_node)

    shaped_edges = _replace_aggregated_edge_refs(selected_edges, ref_replacements)
    aggregation = _aggregation_summary(selected_nodes, shaped_nodes, aggregate_counts)
    return shaped_nodes, shaped_edges, aggregation


def _aggregation_summary(
    selected_nodes: list[dict[str, Any]],
    shaped_nodes: list[dict[str, Any]],
    aggregate_counts: dict[tuple[str, str], int],
) -> dict[str, Any]:
    return {
        "original_node_count": len(selected_nodes),
        "rendered_node_count": len(shaped_nodes),
        "aggregated_node_count": sum(aggregate_counts.values()),
        "aggregate_counts_by_type": {
            node_type: sum(
                count for (_, aggregate_type), count in aggregate_counts.items() if aggregate_type == node_type
            )
            for node_type in sorted({node_type for _, node_type in aggregate_counts})
        },
    }


def _aggregate_key_for_overview_node(
    node: dict[str, Any],
    type_counts: dict[str, int],
    used_security_group_refs: set[str],
) -> tuple[str, str] | None:
    node_type = str(node.get("type") or "")
    if node_type in _STRUCTURAL_NODE_TYPES:
        return None
    node_ref = str(node.get("ref") or node.get("id") or "").strip()
    if node_type == "security_group" and node_ref in used_security_group_refs:
        return None
    limit = _AGGREGATE_TYPE_LIMITS.get(node_type)
    if limit is None or type_counts.get(node_type, 0) <= limit:
        return None
    service = str(node.get("service") or "aws").strip() or "aws"
    return service, node_type


def _aggregate_ref(aggregate_key: tuple[str, str]) -> str:
    service, node_type = aggregate_key
    return _safe_cell_id(f"agg_{service}_{node_type}", fallback="agg_node")


def _aggregate_label(node_type: str, count: int) -> str:
    label = node_type.replace("_", " ")
    if node_type == "cidr":
        label = "CIDR sources"
    elif node_type == "security_group":
        label = "Other security groups"
    elif node_type == "dynamodb_table":
        label = "DynamoDB tables"
    elif node_type == "s3_bucket":
        label = "S3 buckets"
    elif node_type == "codepipeline":
        label = "CodePipeline pipelines"
    elif node_type == "ecr_repository":
        label = "ECR repositories"
    elif node_type == "sqs_queue":
        label = "SQS queues"
    elif node_type == "sns_topic":
        label = "SNS topics"
    elif node_type == "secrets_manager_secret":
        label = "Secrets Manager secrets"
    elif node_type == "lambda_function":
        label = "Lambda functions"
    elif node_type == "step_function":
        label = "Step Functions"
    elif node_type == "eventbridge_bus":
        label = "EventBridge buses"
    return f"{count} {label}" if count else label


def _replace_aggregated_edge_refs(
    selected_edges: list[dict[str, Any]],
    ref_replacements: dict[str, str],
) -> list[dict[str, Any]]:
    shaped_edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for edge in selected_edges:
        source = str(edge.get("source_ref") or edge.get("source") or "").strip()
        target = str(edge.get("target_ref") or edge.get("target") or "").strip()
        next_source = ref_replacements.get(source, source)
        next_target = ref_replacements.get(target, target)
        if not next_source or not next_target or next_source == next_target:
            continue
        next_edge = dict(edge)
        if "source_ref" in next_edge or "target_ref" in next_edge:
            next_edge["source_ref"] = next_source
            next_edge["target_ref"] = next_target
        else:
            next_edge["source"] = next_source
            next_edge["target"] = next_target
        edge_key = (
            next_source,
            next_target,
            str(next_edge.get("type") or ""),
            _edge_value(str(next_edge.get("type") or ""), next_edge),
        )
        if edge_key in seen:
            continue
        seen.add(edge_key)
        shaped_edges.append(next_edge)
    return shaped_edges
