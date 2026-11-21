"""Per-service summary of an AWS topology snapshot."""

from __future__ import annotations

from typing import Any

IDENTITY_ONLY_SERVICES = {"sts"}
CATALOG_ONLY_SERVICES = {"bedrock"}

_INTERPRETATION_NOTES = (
    "Topology inventory shows visible resources and catalog visibility, not proof of recent runtime usage.",
    "Use Cost Explorer, CloudTrail, or service metrics when the user asks for confirmed active usage.",
    "STS account identity and Bedrock model catalog visibility are evidence context, not workload usage by themselves.",
)


def _count_by(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(field) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _compact_warnings_by_service(warnings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    compact: dict[str, list[dict[str, Any]]] = {}
    for warning in warnings:
        bucket = compact.setdefault(str(warning.get("service") or "unknown"), [])
        if len(bucket) < 5:
            bucket.append(
                {
                    "operation": warning.get("operation"),
                    "severity": warning.get("severity") or "warning",
                    "reason": warning.get("reason"),
                    "message": str(warning.get("message") or "")[:300],
                }
            )
    return compact


def _service_coverage(
    requested: list[str],
    *,
    node_counts_by_service: dict[str, int],
    succeeded: set[str],
    failed: set[str],
) -> dict[str, Any]:
    with_nodes = {service for service, count in node_counts_by_service.items() if count > 0}
    return {
        "services_partial": sorted(service for service in requested if service in succeeded and service in failed),
        "services_with_nodes": sorted(with_nodes),
        "inventory_services_with_resources": sorted(with_nodes - IDENTITY_ONLY_SERVICES - CATALOG_ONLY_SERVICES),
        "identity_evidence_services": sorted(with_nodes & IDENTITY_ONLY_SERVICES),
        "catalog_visibility_services": sorted(with_nodes & CATALOG_ONLY_SERVICES),
        "services_checked_no_resources": sorted(
            service
            for service in requested
            if service in succeeded and service not in with_nodes and service not in failed
        ),
    }


def build_topology_service_summary(
    *,
    account_id: str,
    region: str,
    services_requested: list[str],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    services_succeeded: set[str],
    services_failed: set[str],
    services_skipped: set[str],
) -> dict[str, Any]:
    node_counts_by_service = _count_by(nodes, "service")
    requested = list(services_requested)
    coverage = _service_coverage(
        requested,
        node_counts_by_service=node_counts_by_service,
        succeeded=set(services_succeeded),
        failed=set(services_failed),
    )
    return {
        "evidence_kind": "aws_topology_inventory",
        "account_id": account_id,
        "region": region,
        "resource_node_count": len(nodes),
        "edge_count": len(edges),
        "services_requested": requested,
        "services_succeeded": sorted(services_succeeded),
        "services_failed": sorted(services_failed),
        "services_skipped": sorted(services_skipped),
        **coverage,
        "node_counts_by_service": dict(sorted(node_counts_by_service.items())),
        "node_counts_by_type": dict(sorted(_count_by(nodes, "type").items())),
        "edge_counts_by_service": dict(sorted(_count_by(edges, "service").items())),
        "warning_count": len(warnings),
        "warning_counts_by_service": dict(sorted(_count_by(warnings, "service").items())),
        "warnings_by_service": dict(sorted(_compact_warnings_by_service(warnings).items())),
        "interpretation_notes": list(_INTERPRETATION_NOTES),
    }
