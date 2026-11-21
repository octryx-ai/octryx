from __future__ import annotations

from typing import Any

from app.services.tool_result_compression.budget import COMPACT_RESULT_TOKEN_BUDGET_KEY
from app.services.tool_result_compression.config import clamp_config_int

from ..prompt_catalog import render_prompt

_DIAGRAM_NODE_TYPE_PRIORITY = (
    "aws_account",
    "vpc",
    "subnet",
    "internet_gateway",
    "nat_gateway",
    "transit_gateway",
    "vpc_peering",
    "vpc_endpoint",
    "route_table",
    "cloudfront_distribution",
    "route53_zone",
    "api_gateway",
    "load_balancer",
    "target_group",
    "eks_cluster",
    "eks_nodegroup",
    "ecs_cluster",
    "ecs_service",
    "autoscaling_group",
    "ec2_instance",
    "lambda_function",
    "step_function",
    "rds_proxy",
    "rds_cluster",
    "rds_instance",
    "elasticache_cluster",
    "redshift_cluster",
    "dynamodb_table",
    "efs_file_system",
    "s3_bucket",
    "ecr_repository",
    "sqs_queue",
    "sns_topic",
    "eventbridge_bus",
    "kinesis_stream",
    "msk_cluster",
    "mq_broker",
    "secrets_manager_secret",
    "kms_key",
    "codepipeline",
    "waf_web_acl",
    "security_group",
    "cidr",
)
_DIAGRAM_EDGE_TYPE_PRIORITY = (
    "serves",
    "connects_to",
    "resolves_to",
    "triggers",
    "delivers_to",
    "routes_to",
    "attached_to",
    "protects",
    "runs_in",
    "uses_subnet",
    "uses_route_table",
    "uses_security_group",
    "backs",
    "allows_ingress_to",
    "allows_egress_to",
    "belongs_to",
    "belongs_to_account",
)
_DIAGRAM_CATALOG_ONLY_NODE_TYPES = {"bedrock_model"}
_FULL_DIAGRAM_SERVICE_ORDER = (
    "sts",
    "wafv2",
    "elbv2",
    "ec2",
    "eks",
    "rds",
    "dynamodb",
    "lambda",
    "s3",
    "codepipeline",
)
_FULL_DIAGRAM_RESULT_TOKEN_BUDGET = 50000
_FULL_DIAGRAM_MAX_NODES = 5000
_FULL_DIAGRAM_MAX_EDGES = 10000


def build_aws_topology_diagram_brief(result: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    return _build_diagram_brief(result, dict(config or {}))


def _compress_aws_topology_snapshot(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    if "service_summary" not in result and "nodes" not in result and "edges" not in result:
        return None

    diagram_brief_requested = _diagram_brief_requested(result, config)
    max_nodes_per_service = _clamp_optional_int(config, "max_nodes_per_service", default=0, maximum=20)
    default_warning_limit = 5 if diagram_brief_requested else 20
    max_warnings = clamp_config_int(config, "max_warnings", default=default_warning_limit, minimum=1, maximum=100)
    if diagram_brief_requested:
        max_warnings = min(max_warnings, 5)
    diagram_detail = _diagram_detail(result, config) if diagram_brief_requested else "compact"
    nodes_by_service: dict[str, list[dict[str, Any]]] = {}
    if max_nodes_per_service > 0 and not diagram_brief_requested:
        for node in result.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            service = str(node.get("service") or "unknown")
            bucket = nodes_by_service.setdefault(service, [])
            if len(bucket) >= max_nodes_per_service:
                continue
            bucket.append(
                {
                    "id": node.get("id"),
                    "type": node.get("type"),
                    "label": node.get("label"),
                    "service": service,
                    "region": node.get("region"),
                    "arn": node.get("arn"),
                    "attributes": _compact_attributes(node.get("attributes")),
                }
            )

    warnings = []
    for warning in result.get("warnings") or []:
        if not isinstance(warning, dict):
            continue
        if len(warnings) >= max_warnings:
            break
        warnings.append(
            {
                "service": warning.get("service"),
                "operation": warning.get("operation"),
                "severity": warning.get("severity") or "warning",
                "reason": warning.get("reason"),
                "message": str(warning.get("message") or "")[:500],
            }
        )

    compact = {
        "account_id": result.get("account_id"),
        "region": result.get("region"),
        "generated_at": result.get("generated_at"),
        "service_summary": (
            _compact_diagram_service_summary(result.get("service_summary"))
            if diagram_brief_requested
            else _compact_service_summary(result.get("service_summary"))
        ),
        "scope": (
            _compact_diagram_scope(result.get("scope"))
            if diagram_brief_requested
            else _compact_scope(result.get("scope"))
        ),
        "answer_guidance": _topology_answer_guidance(diagram_brief_requested, diagram_detail=diagram_detail),
        "compression_note": render_prompt("tool_guard.compression.aws.inventory_note"),
    }
    if not diagram_brief_requested:
        compact["sampled_nodes_by_service"] = dict(sorted(nodes_by_service.items()))
        compact["warning_count"] = len(result.get("warnings") or [])
        compact["warnings"] = warnings
        compact["diagram_hints"] = result.get("diagram_hints")
    else:
        compact["diagram_brief"] = _build_diagram_brief(result, config)
        compact["compression_note"] = render_prompt("tool_guard.compression.aws.diagram_note")
        if diagram_detail == "full":
            compact[COMPACT_RESULT_TOKEN_BUDGET_KEY] = clamp_config_int(
                config,
                "full_diagram_result_token_budget",
                default=_FULL_DIAGRAM_RESULT_TOKEN_BUDGET,
                minimum=3000,
                maximum=_FULL_DIAGRAM_RESULT_TOKEN_BUDGET,
            )
    return compact


def _diagram_brief_requested(result: dict[str, Any], config: dict[str, Any]) -> bool:
    scope = result.get("scope") if isinstance(result, dict) else {}
    if isinstance(scope, dict) and scope.get("diagram_brief_requested"):
        return True
    return bool((config or {}).get("include_diagram_brief"))


def _diagram_detail(result: dict[str, Any], config: dict[str, Any]) -> str:
    scope = result.get("scope") if isinstance(result, dict) else {}
    raw_detail = ""
    if isinstance(scope, dict):
        raw_detail = str(scope.get("diagram_detail") or "").strip().lower()
    if not raw_detail and isinstance(config, dict):
        raw_detail = str(config.get("diagram_detail") or "").strip().lower()
    if raw_detail in {"full", "overview", "complete"}:
        return "full"
    return "compact"


def _build_diagram_brief(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    nodes = [node for node in (result.get("nodes") or []) if isinstance(node, dict)]
    edges = [edge for edge in (result.get("edges") or []) if isinstance(edge, dict)]
    diagram_detail = _diagram_detail(result, config)
    full_overview = diagram_detail == "full"
    max_nodes = clamp_config_int(
        config,
        "max_diagram_nodes",
        default=1000 if full_overview else 8,
        minimum=4,
        maximum=_FULL_DIAGRAM_MAX_NODES if full_overview else 40,
    )
    max_edges = clamp_config_int(
        config,
        "max_diagram_edges",
        default=2000 if full_overview else 8,
        minimum=1,
        maximum=_FULL_DIAGRAM_MAX_EDGES if full_overview else 40,
    )
    node_lookup = {str(node.get("id") or ""): node for node in nodes if str(node.get("id") or "").strip()}
    selected_ids = (
        _select_full_overview_node_ids(result, nodes, edges, node_lookup, max_nodes)
        if full_overview
        else _select_compact_diagram_node_ids(nodes, edges, node_lookup, max_nodes)
    )
    selected_id_set = set(selected_ids)
    node_refs = {node_id_value: f"n{index + 1}" for index, node_id_value in enumerate(selected_ids)}
    selected_edges = [
        _compact_diagram_edge(edge, node_lookup, node_refs if full_overview else None)
        for edge in sorted(edges, key=_diagram_edge_sort_key)
        if str(edge.get("source") or "") in selected_id_set and str(edge.get("target") or "") in selected_id_set
    ][:max_edges]
    notes = [render_prompt("tool_guard.compression.aws.brief.selected_edges")]
    if full_overview:
        notes.append(render_prompt("tool_guard.compression.aws.brief.full_overview"))
        notes.append(render_prompt("tool_guard.compression.aws.brief.node_refs"))
    else:
        notes.append(render_prompt("tool_guard.compression.aws.brief.compact"))
    notes.append(render_prompt("tool_guard.compression.aws.brief.aggregate"))
    if any(str(node.get("type") or "") in _DIAGRAM_CATALOG_ONLY_NODE_TYPES for node in nodes):
        notes.append(render_prompt("tool_guard.compression.aws.brief.catalog_only"))
    if len(nodes) > len(selected_ids):
        notes.append(f"{len(nodes) - len(selected_ids)} nodes omitted from this diagram brief.")
    if len(edges) > len(selected_edges):
        notes.append(f"{len(edges) - len(selected_edges)} edges omitted from this diagram brief.")
    return {
        "mode": diagram_detail,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "selected_nodes": [
            _compact_diagram_node(
                node_lookup[node_id_value],
                ref=node_refs[node_id_value] if full_overview else None,
                include_id=not full_overview,
            )
            for node_id_value in selected_ids
        ],
        "selected_edges": selected_edges,
        "service_coverage": _diagram_service_coverage(result, selected_ids, node_lookup),
        "notes": notes,
    }


def _select_compact_diagram_node_ids(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_lookup: dict[str, dict[str, Any]],
    max_nodes: int,
) -> list[str]:
    selected_ids: list[str] = []

    def add_node_id(node_id_value: Any) -> None:
        node_id_text = str(node_id_value or "").strip()
        if not node_id_text or node_id_text in selected_ids or node_id_text not in node_lookup:
            return
        selected_ids.append(node_id_text)

    initial_node_limit = max(6, max_nodes // 2)
    for node in sorted(nodes, key=_diagram_node_sort_key):
        if len(selected_ids) >= initial_node_limit:
            break
        if str(node.get("type") or "") in _DIAGRAM_CATALOG_ONLY_NODE_TYPES:
            continue
        add_node_id(node.get("id"))

    for edge in sorted(edges, key=_diagram_edge_sort_key):
        if len(selected_ids) >= max_nodes:
            break
        add_node_id(edge.get("source"))
        if len(selected_ids) >= max_nodes:
            break
        add_node_id(edge.get("target"))

    for node in sorted(nodes, key=_diagram_node_sort_key):
        if len(selected_ids) >= max_nodes:
            break
        if str(node.get("type") or "") in _DIAGRAM_CATALOG_ONLY_NODE_TYPES:
            continue
        add_node_id(node.get("id"))
    return selected_ids


def _select_full_overview_node_ids(
    result: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_lookup: dict[str, dict[str, Any]],
    max_nodes: int,
) -> list[str]:
    selected_ids: list[str] = []
    service_summary = result.get("service_summary") if isinstance(result.get("service_summary"), dict) else {}
    services_with_resources = [
        str(service)
        for service in (service_summary.get("inventory_services_with_resources") or [])
        if str(service).strip()
    ]
    service_order = [
        service
        for service in _FULL_DIAGRAM_SERVICE_ORDER
        if service in services_with_resources or service == "sts"
    ]
    service_order.extend(
        service
        for service in sorted({str(node.get("service") or "unknown") for node in nodes})
        if service not in service_order and service != "bedrock"
    )

    def add_node_id(node_id_value: Any) -> None:
        node_id_text = str(node_id_value or "").strip()
        if not node_id_text or node_id_text in selected_ids or node_id_text not in node_lookup:
            return
        node = node_lookup[node_id_text]
        if str(node.get("type") or "") in _DIAGRAM_CATALOG_ONLY_NODE_TYPES:
            return
        if len(selected_ids) < max_nodes:
            selected_ids.append(node_id_text)

    for node in sorted(nodes, key=_diagram_node_sort_key):
        if str(node.get("type") or "") in {"aws_account", "vpc"}:
            add_node_id(node.get("id"))

    service_count = max(1, len([service for service in service_order if service != "bedrock"]))
    per_service_limit = max(2, min(12, max_nodes // service_count))
    for service in service_order:
        if service == "bedrock":
            continue
        added_for_service = 0
        for node in sorted(nodes, key=_diagram_node_sort_key):
            if len(selected_ids) >= max_nodes or added_for_service >= per_service_limit:
                break
            if str(node.get("service") or "") != service:
                continue
            before_count = len(selected_ids)
            add_node_id(node.get("id"))
            if len(selected_ids) > before_count:
                added_for_service += 1

    for edge in sorted(edges, key=_diagram_edge_sort_key):
        if len(selected_ids) >= max_nodes:
            break
        if str(edge.get("service") or "") == "bedrock":
            continue
        add_node_id(edge.get("source"))
        if len(selected_ids) >= max_nodes:
            break
        add_node_id(edge.get("target"))

    for node in sorted(nodes, key=_diagram_node_sort_key):
        if len(selected_ids) >= max_nodes:
            break
        add_node_id(node.get("id"))

    return selected_ids


def _diagram_node_sort_key(node: dict[str, Any]) -> tuple[int, str, str]:
    node_type = str(node.get("type") or "")
    try:
        rank = _DIAGRAM_NODE_TYPE_PRIORITY.index(node_type)
    except ValueError:
        rank = len(_DIAGRAM_NODE_TYPE_PRIORITY)
    return (rank, str(node.get("service") or ""), str(node.get("label") or node.get("id") or ""))


def _diagram_edge_sort_key(edge: dict[str, Any]) -> tuple[int, str, str, str]:
    edge_type = str(edge.get("type") or "")
    try:
        rank = _DIAGRAM_EDGE_TYPE_PRIORITY.index(edge_type)
    except ValueError:
        rank = len(_DIAGRAM_EDGE_TYPE_PRIORITY)
    return (
        rank,
        str(edge.get("service") or ""),
        str(edge.get("source") or ""),
        str(edge.get("target") or ""),
    )


def _compact_diagram_node(node: dict[str, Any], *, ref: str | None = None, include_id: bool = True) -> dict[str, Any]:
    compact = {
        "type": node.get("type"),
        "label": node.get("label"),
        "service": node.get("service"),
        "region": node.get("region"),
    }
    name_tag = str((node.get("tags") or {}).get("Name") or "").strip()
    if name_tag and name_tag != compact["label"]:
        compact["name"] = name_tag
    attributes = _compact_attributes(node.get("attributes"))
    if attributes:
        compact["attributes"] = attributes
    if ref:
        compact = {"ref": ref, **compact}
    if include_id:
        compact = {"id": node.get("id"), **compact}
    return compact


def _compact_diagram_edge(
    edge: dict[str, Any],
    node_lookup: dict[str, dict[str, Any]],
    node_refs: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = str(edge.get("source") or "")
    target = str(edge.get("target") or "")
    compact = {
        "source": source,
        "source_label": (node_lookup.get(source) or {}).get("label"),
        "target": target,
        "target_label": (node_lookup.get(target) or {}).get("label"),
        "type": edge.get("type"),
        "service": edge.get("service"),
    }
    attributes = _compact_edge_attributes(edge.get("attributes"))
    if attributes:
        compact["attributes"] = attributes
    if node_refs:
        compact.pop("source", None)
        compact.pop("target", None)
        compact["source_ref"] = node_refs.get(source)
        compact["target_ref"] = node_refs.get(target)
    return compact


def _diagram_service_coverage(
    result: dict[str, Any],
    selected_ids: list[str],
    node_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    service_summary = result.get("service_summary") if isinstance(result.get("service_summary"), dict) else {}
    selected_counts: dict[str, int] = {}
    for node_id_value in selected_ids:
        service = str((node_lookup.get(node_id_value) or {}).get("service") or "unknown")
        selected_counts[service] = selected_counts.get(service, 0) + 1
    return {
        "inventory_services_with_resources": service_summary.get("inventory_services_with_resources") or [],
        "node_counts_by_service": service_summary.get("node_counts_by_service") or {},
        "selected_node_counts_by_service": dict(sorted(selected_counts.items())),
    }


def _topology_answer_guidance(diagram_brief_requested: bool, *, diagram_detail: str = "compact") -> list[str]:
    if diagram_brief_requested:
        guidance = [
            render_prompt("tool_guard.compression.aws.guidance.diagram_relationships"),
            render_prompt("tool_guard.compression.aws.guidance.no_invented_chains"),
        ]
        if diagram_detail == "full":
            guidance.append(render_prompt("tool_guard.compression.aws.guidance.full_overview"))
        else:
            guidance.append(render_prompt("tool_guard.compression.aws.guidance.compact"))
        return guidance
    return [
        render_prompt("tool_guard.compression.aws.guidance.inventory_only"),
        render_prompt("tool_guard.compression.aws.guidance.no_usage_claims"),
        render_prompt("tool_guard.compression.aws.guidance.partial_services"),
        render_prompt("tool_guard.compression.aws.guidance.concise"),
    ]


def _compact_service_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "evidence_kind",
        "account_id",
        "region",
        "resource_node_count",
        "edge_count",
        "inventory_services_with_resources",
        "identity_evidence_services",
        "catalog_visibility_services",
        "services_checked_no_resources",
        "services_partial",
        "services_failed",
        "services_skipped",
        "node_counts_by_service",
        "node_counts_by_type",
        "warning_count",
        "warning_counts_by_service",
        "warnings_by_service",
        "interpretation_notes",
    )
    return {key: value.get(key) for key in keys if key in value}


def _compact_diagram_service_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "evidence_kind",
        "account_id",
        "region",
        "resource_node_count",
        "edge_count",
        "inventory_services_with_resources",
        "node_counts_by_service",
        # full per-type counts feed the service-inventory board (true totals,
        # independent of the bounded diagram_brief selection)
        "node_counts_by_type",
    )
    compact = {key: value.get(key) for key in keys if key in value}
    if value.get("services_failed"):
        compact["services_failed"] = value.get("services_failed")
    if value.get("services_partial"):
        compact["services_partial"] = value.get("services_partial")
    if value.get("services_skipped"):
        # policy-blocked services surface in the diagram legend as coverage gaps
        compact["services_skipped"] = value.get("services_skipped")
    return compact


def _compact_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "services_requested",
        "services_succeeded",
        "services_failed",
        "services_skipped",
        "max_items",
        "max_nodes",
        "diagram_brief_requested",
    )
    return {key: value.get(key) for key in keys if key in value}


def _compact_diagram_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = ("max_items", "max_nodes", "diagram_brief_requested", "diagram_detail")
    return {key: value.get(key) for key in keys if key in value}


def _clamp_optional_int(config: dict[str, Any], key: str, *, default: int, maximum: int) -> int:
    raw_value = config.get(key) if isinstance(config, dict) else None
    try:
        parsed = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, maximum))


def _compact_attributes(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    interesting_keys = (
        "status",
        "state",
        "engine",
        "type",
        "scheme",
        "vpc_id",
        "availability_zone",
        "cidr_block",
        "route_table_id",
        "subnet_tier",
        "subnet_tier_source",
        "is_default",
        "billing_mode",
        "item_count",
        "stream_enabled",
        "cluster_name",
        "desired_size",
        "min_size",
        "max_size",
        "instance_types",
        "capacity_type",
        "publicly_accessible",
        "endpoint_public_access",
        "endpoint_private_access",
        "runtime",
        "provider_name",
        "listeners",
        # extended-service attributes
        "api_type",
        "instance_type",
        "launch_type",
        "desired_count",
        "running_count",
        "node_count",
        "node_type",
        "engine_family",
        "record_count",
        "private",
        "domain",
        "endpoint_type",
        "resource_type",
        "size_bytes",
    )
    return {key: value.get(key) for key in interesting_keys if key in value}


def _compact_edge_attributes(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    interesting_keys = (
        "protocol",
        "from_port",
        "to_port",
        "destination",
        "source_type",
        "target_type",
        "source_description",
        "target_description",
        "listeners",
    )
    return {key: value.get(key) for key in interesting_keys if key in value}
