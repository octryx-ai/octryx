from __future__ import annotations

from typing import Any

from app.services.database_tool.common import DATABASE_TOOL_PREFIX

CONTRACT_VERSION = 1
CODE_GRAPH_TOOLS = {
    "code_affected",
    "code_callees",
    "code_context",
    "code_explore",
    "code_files",
    "code_god_nodes",
    "code_graph_stats",
    "code_graph_status",
    "code_graph_summary",
    "code_impact",
    "code_neighbors",
    "code_node",
    "code_trace",
}
AWS_INTELLIGENCE_TOOLS = {
    "aws_config_query",
    "aws_cost_topology_report",
    "aws_deployment_timeline",
    "aws_exposure_map",
    "aws_incident_evidence_bundle",
    "aws_network_path_analyzer",
    "aws_runtime_vs_iac_drift",
    "aws_security_posture_summary",
    "aws_topology_diff",
    "aws_trusted_advisor_summary",
    "aws_well_architected_assessment",
}


def attach_evidence_contract(
    *,
    tool_name: str,
    original_result: dict[str, Any],
    compressed_result: dict[str, Any],
    strategy: str,
) -> dict[str, Any]:
    contract = _evaluate_contract(
        tool_name=tool_name,
        original_result=original_result,
        compressed_result=compressed_result,
        strategy=strategy,
    )
    if contract is None:
        return compressed_result
    enriched = dict(compressed_result)
    enriched["evidence_contract"] = contract
    return enriched


def _evaluate_contract(
    *,
    tool_name: str,
    original_result: dict[str, Any],
    compressed_result: dict[str, Any],
    strategy: str,
) -> dict[str, Any] | None:
    normalized_tool_name = str(tool_name or "").strip()
    if normalized_tool_name.startswith(DATABASE_TOOL_PREFIX):
        return _database_query_contract(normalized_tool_name, compressed_result, strategy=strategy)
    if normalized_tool_name == "aws_topology_snapshot":
        return _topology_contract(original_result, compressed_result, strategy=strategy)
    if normalized_tool_name == "kubernetes_topology_snapshot":
        return _kubernetes_topology_contract(compressed_result, strategy=strategy)
    if normalized_tool_name in CODE_GRAPH_TOOLS:
        return _code_graph_contract(normalized_tool_name, compressed_result, strategy=strategy)
    if normalized_tool_name in AWS_INTELLIGENCE_TOOLS:
        return _aws_intelligence_contract(normalized_tool_name, compressed_result, strategy=strategy)
    if normalized_tool_name == "search_confluence":
        return _required_field_contract(
            tool_name=normalized_tool_name,
            result=compressed_result,
            required_paths=("query", "total", "result_count", "results"),
            strategy=strategy,
        )
    if normalized_tool_name == "get_confluence_page":
        return _required_field_contract(
            tool_name=normalized_tool_name,
            result=compressed_result,
            required_paths=("id", "title", "space_key", "version", "url", "headings", "excerpt", "text_length"),
            strategy=strategy,
        )
    return None


def _topology_contract(
    original_result: dict[str, Any],
    compressed_result: dict[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    required_paths = [
        "account_id",
        "region",
        "generated_at",
        "service_summary",
        "service_summary.inventory_services_with_resources",
        "service_summary.node_counts_by_service",
        "scope",
        "answer_guidance",
    ]
    if _diagram_brief_expected(original_result, compressed_result):
        required_paths.extend(
            [
                "diagram_brief",
                "diagram_brief.mode",
                "diagram_brief.node_count",
                "diagram_brief.edge_count",
                "diagram_brief.selected_nodes",
                "diagram_brief.selected_edges",
                "diagram_brief.service_coverage",
            ]
        )
    return _required_field_contract(
        tool_name="aws_topology_snapshot",
        result=compressed_result,
        required_paths=tuple(required_paths),
        strategy=strategy,
    )


def _kubernetes_topology_contract(
    compressed_result: dict[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    required_paths = (
        "source",
        "generated_at",
        "scope",
        "topology_summary",
        "topology_summary.resource_node_count",
        "topology_summary.edge_count",
        "topology_summary.selected_resource_node_count",
        "topology_summary.selected_edge_count",
        "topology_summary.node_counts_by_type",
        "diagram_brief",
        "diagram_brief.mode",
        "diagram_brief.selected_nodes",
        "diagram_brief.selected_edges",
        "diagram_brief.omitted_node_count",
        "diagram_brief.omitted_edge_count",
        "answer_guidance",
    )
    allow_empty_paths = []
    if _safe_int(_nested_value(compressed_result, "topology_summary.resource_node_count")) == 0:
        allow_empty_paths.append("topology_summary.node_counts_by_type")
    if _safe_int(_nested_value(compressed_result, "topology_summary.selected_resource_node_count")) == 0:
        allow_empty_paths.append("diagram_brief.selected_nodes")
    if _safe_int(_nested_value(compressed_result, "topology_summary.selected_edge_count")) == 0:
        allow_empty_paths.append("diagram_brief.selected_edges")
    return _required_field_contract(
        tool_name="kubernetes_topology_snapshot",
        result=compressed_result,
        required_paths=required_paths,
        strategy=strategy,
        allow_empty_paths=tuple(allow_empty_paths),
    )


def _database_query_contract(
    tool_name: str,
    compressed_result: dict[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    required_paths = (
        "tool_name",
        "connector_name",
        "db_type",
        "row_count",
        "max_rows",
        "rows",
        "applied_rls_rules",
    )
    allow_empty_paths = ["applied_rls_rules"]
    if _safe_int(compressed_result.get("row_count")) == 0:
        allow_empty_paths.append("rows")
    return _required_field_contract(
        tool_name=tool_name,
        result=compressed_result,
        required_paths=required_paths,
        strategy=strategy,
        allow_empty_paths=tuple(allow_empty_paths),
    )


def _code_graph_contract(
    tool_name: str,
    compressed_result: dict[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    if compressed_result.get("context_format") == "cited_code_packet":
        required = ("status", "repository.id", "graph.run_id", "graph.backend", "graph.status",
                    "start_node", "context_nodes", "source_chunks", "context_edges", "omitted", "model_budget")
        allow_empty = ["context_nodes", "context_edges", "omitted"]
        if compressed_result.get("status") in {"graph_not_indexed", "node_not_found"}:
            required = ("status", "context_nodes", "source_chunks", "context_edges", "omitted", "model_budget")
            allow_empty.append("source_chunks")
        return _required_field_contract(
            tool_name=tool_name, result=compressed_result, required_paths=required,
            strategy=strategy, allow_empty_paths=tuple(allow_empty),
        )
    required_paths = ["graph", "graph.status"]
    allow_empty_paths: list[str] = []
    allow_none_paths: list[str] = []
    status = str(compressed_result.get("status") or "").strip()
    if status != "graph_not_indexed":
        required_paths.extend(
            [
                "repository",
                "graph_backend",
                "graph.backend",
                "graph.node_count",
                "graph.edge_count",
            ]
        )

    _extend_code_graph_tool_paths(
        tool_name=tool_name,
        result=compressed_result,
        required_paths=required_paths,
        allow_empty_paths=allow_empty_paths,
        allow_none_paths=allow_none_paths,
    )
    return _required_field_contract(
        tool_name=tool_name,
        result=compressed_result,
        required_paths=tuple(dict.fromkeys(required_paths)),
        strategy=strategy,
        allow_empty_paths=tuple(allow_empty_paths),
        allow_none_paths=tuple(allow_none_paths),
    )


def _extend_code_graph_tool_paths(
    *,
    tool_name: str,
    result: dict[str, Any],
    required_paths: list[str],
    allow_empty_paths: list[str],
    allow_none_paths: list[str],
) -> None:
    status = str(result.get("status") or "").strip()
    if tool_name == "code_node":
        required_paths.extend(["matches", "match_count", "query"])
        allow_empty_paths.extend(["matches", "detail"])
        if _safe_int(result.get("match_count")) and _safe_int(result.get("match_count")) > 0:
            required_paths.extend(["node", "detail"])
        else:
            required_paths.append("node")
            allow_none_paths.append("node")
        return
    if tool_name in {"code_neighbors", "code_callees"}:
        required_paths.extend(["status", "start_node", "nodes", "edges", "limits"])
        allow_empty_paths.extend(["nodes", "edges"])
        if tool_name == "code_callees":
            required_paths.extend(["callees", "semantics"])
            allow_empty_paths.append("callees")
        if status == "node_not_found":
            allow_none_paths.append("start_node")
        return
    if tool_name == "code_trace":
        required_paths.extend(["status", "source_node", "target_node", "path", "edges"])
        allow_empty_paths.extend(["path", "edges"])
        if status in {"ready", "no_path"}:
            required_paths.extend(["hops", "hop_count", "truncated", "no_path_reason", "limits"])
            allow_empty_paths.append("hops")
        if status == "endpoint_not_found":
            allow_none_paths.extend(["source_node", "target_node"])
        return
    if tool_name == "code_graph_stats":
        required_paths.extend(["status", "stats", "node_types", "relations", "top_degree_nodes", "limits"])
        allow_empty_paths.extend(["node_types", "relations", "top_degree_nodes"])
        return
    if tool_name == "code_graph_status":
        required_paths.extend(["status", "latest_run", "staleness_warnings"])
        allow_empty_paths.append("staleness_warnings")
        return
    if tool_name == "code_god_nodes":
        required_paths.extend(["status", "nodes", "count", "filters", "limits"])
        if _safe_int(result.get("count")) == 0:
            allow_empty_paths.append("nodes")
        return
    if tool_name in {"code_affected", "code_impact"}:
        required_paths.extend(["status", "start_node", "affected_nodes", "affected_files", "edges", "semantics"])
        required_paths.extend(["filters", "limits"])
        allow_empty_paths.extend(["affected_nodes", "affected_files", "edges"])
        if status == "node_not_found":
            allow_none_paths.append("start_node")
        return
    if tool_name == "code_files":
        required_paths.extend(["status", "files", "count", "filters"])
        if _safe_int(result.get("count")) == 0:
            allow_empty_paths.append("files")
        return
    if tool_name in {"code_context", "code_explore"}:
        required_paths.extend(
            [
                "status",
                "start_node",
                "context_nodes",
                "context_edges",
                "context_files",
                "relationship_map",
                "budget",
                "retrieval_provenance",
                "filters",
                "limits",
            ]
        )
        allow_empty_paths.extend(["context_nodes", "context_edges", "context_files", "relationship_map"])
        if status == "node_not_found":
            allow_none_paths.append("start_node")
        return
    if tool_name == "code_graph_summary":
        required_paths.extend(["repository"])


def _aws_intelligence_contract(
    tool_name: str,
    compressed_result: dict[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    required_paths = ["status"]
    allow_empty_paths: list[str] = []
    status = str(compressed_result.get("status") or "").strip()
    if status != "ok":
        if "error" in compressed_result:
            required_paths.append("error")
        if "warnings" in compressed_result:
            required_paths.append("warnings")
            allow_empty_paths.append("warnings")
        return _required_field_contract(
            tool_name=tool_name,
            result=compressed_result,
            required_paths=tuple(required_paths),
            strategy=strategy,
            allow_empty_paths=tuple(allow_empty_paths),
        )

    _extend_aws_intelligence_paths(
        tool_name=tool_name,
        required_paths=required_paths,
        allow_empty_paths=allow_empty_paths,
    )
    return _required_field_contract(
        tool_name=tool_name,
        result=compressed_result,
        required_paths=tuple(dict.fromkeys(required_paths)),
        strategy=strategy,
        allow_empty_paths=tuple(allow_empty_paths),
    )


def _extend_aws_intelligence_paths(
    *,
    tool_name: str,
    required_paths: list[str],
    allow_empty_paths: list[str],
) -> None:
    if tool_name == "aws_trusted_advisor_summary":
        required_paths.extend(["summary", "checks", "check_results", "warnings"])
        allow_empty_paths.extend(["checks", "check_results", "warnings"])
        return
    if tool_name == "aws_security_posture_summary":
        required_paths.extend(["topology_source", "summary", "findings", "warnings"])
        allow_empty_paths.extend(["findings", "warnings"])
        return
    if tool_name == "aws_exposure_map":
        required_paths.extend(["topology_source", "summary", "public_sources", "exposed_nodes", "exposure_edges"])
        required_paths.append("warnings")
        allow_empty_paths.extend(["public_sources", "exposed_nodes", "exposure_edges", "warnings"])
        return
    if tool_name == "aws_deployment_timeline":
        required_paths.extend(["sources", "pipeline_names", "summary", "events", "warnings"])
        allow_empty_paths.extend(["pipeline_names", "events", "warnings"])
        return
    if tool_name == "aws_cost_topology_report":
        required_paths.extend(
            [
                "period",
                "metric",
                "topology_source",
                "summary",
                "service_costs",
                "topology_allocations",
                "tag_costs",
                "unmapped_costs",
                "warnings",
            ]
        )
        allow_empty_paths.extend(["service_costs", "topology_allocations", "tag_costs", "unmapped_costs", "warnings"])
        return
    if tool_name == "aws_incident_evidence_bundle":
        required_paths.extend(["incident", "summary", "sections", "redactions", "warnings"])
        allow_empty_paths.extend(["sections", "redactions", "warnings"])
        return
    if tool_name == "aws_well_architected_assessment":
        required_paths.extend(["basis", "summary", "pillars", "checks", "warnings"])
        allow_empty_paths.append("warnings")
        return
    if tool_name == "aws_config_query":
        required_paths.extend(
            ["service", "operation", "query", "limit", "result_count", "items", "evidence", "warnings"]
        )
        allow_empty_paths.extend(["items", "warnings"])
        return
    if tool_name == "aws_network_path_analyzer":
        required_paths.extend(
            [
                "topology_source",
                "source_node_id",
                "target_node_id",
                "reachability",
                "analysis_basis",
                "max_depth",
                "path_count",
                "paths",
                "exposure_notes",
                "warnings",
            ]
        )
        allow_empty_paths.extend(["paths", "exposure_notes", "warnings"])
        return
    if tool_name == "aws_topology_diff":
        required_paths.extend(["baseline", "candidate", "summary", "service_summary", "node_diffs", "edge_diffs"])
        required_paths.append("warnings")
        allow_empty_paths.extend(["service_summary", "node_diffs", "edge_diffs", "warnings"])
        return
    if tool_name == "aws_runtime_vs_iac_drift":
        required_paths.extend(
            [
                "expected_source",
                "runtime_source",
                "expected",
                "runtime",
                "summary",
                "service_summary",
                "drift_items",
                "warnings",
            ]
        )
        allow_empty_paths.extend(["service_summary", "drift_items", "warnings"])


def _required_field_contract(
    *,
    tool_name: str,
    result: dict[str, Any],
    required_paths: tuple[str, ...],
    strategy: str,
    allow_empty_paths: tuple[str, ...] = (),
    allow_none_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    empty_allowed = set(allow_empty_paths)
    none_allowed = set(allow_none_paths)
    missing_paths = [
        path
        for path in required_paths
        if not _has_path(result, path, allow_empty=path in empty_allowed, allow_none=path in none_allowed)
    ]
    hard_capped = _contains_hard_cap_marker(result)
    status = "passed" if not missing_paths and not hard_capped else "failed"
    return {
        "version": CONTRACT_VERSION,
        "tool_name": tool_name,
        "strategy": strategy,
        "status": status,
        "required_paths": list(required_paths),
        "missing_paths": missing_paths,
        "hard_capped": hard_capped,
        "evidence_state": "compact_evidence" if status == "passed" else "incomplete_compact_evidence",
    }


def _diagram_brief_expected(original_result: dict[str, Any], compressed_result: dict[str, Any]) -> bool:
    scope = original_result.get("scope") if isinstance(original_result.get("scope"), dict) else {}
    compact_scope = compressed_result.get("scope") if isinstance(compressed_result.get("scope"), dict) else {}
    return bool(scope.get("diagram_brief_requested") or compact_scope.get("diagram_brief_requested"))


def _has_path(value: Any, path: str, *, allow_empty: bool = False, allow_none: bool = False) -> bool:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current.get(part)
    if current is None:
        if allow_none:
            return True
        return False
    if not allow_empty and isinstance(current, (str, list, dict)) and len(current) == 0:
        return False
    return True


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_value(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _contains_hard_cap_marker(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("_hard_capped") is True:
            return True
        return any(_contains_hard_cap_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_hard_cap_marker(item) for item in value)
    return False


__all__ = ["attach_evidence_contract"]
