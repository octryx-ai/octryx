"""AWS runtime versus IaC drift connector tool."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_topology import build_aws_topology_snapshot
from .aws_topology_common import compact_payload, node_id
from .aws_topology_diff import compare_aws_topology_snapshots
from .common import _string

HIGH_IMPACT_TYPES = {"eks_cluster", "rds_instance", "vpc", "subnet", "load_balancer", "waf_web_acl"}


def _snapshot_from_params(params: dict[str, Any], *names: str) -> dict[str, Any] | None:
    for name in names:
        value = params.get(name)
        if isinstance(value, dict):
            return value
    return None


def _resource_id(resource: dict[str, Any]) -> str:
    explicit = _string(resource.get("id"))
    if explicit:
        return explicit
    resource_type = _string(resource.get("type")) or _string(resource.get("resource_type")) or "iac_resource"
    value = (
        _string(resource.get("arn"))
        or _string(resource.get("resource_id"))
        or _string(resource.get("name"))
        or _string(resource.get("label"))
    )
    return node_id(resource_type, value or "unknown")


def _expected_snapshot_from_resources(resources: list[Any], params: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    warnings = []
    for item in resources:
        if not isinstance(item, dict):
            warnings.append({"severity": "warning", "message": "Ignored non-object IaC resource entry."})
            continue
        service = _string(item.get("service")) or _string(item.get("provider")) or "iac"
        resource_type = _string(item.get("type")) or _string(item.get("resource_type")) or "iac_resource"
        label = _string(item.get("label")) or _string(item.get("name")) or _resource_id(item)
        nodes.append(
            {
                "id": _resource_id(item),
                "type": resource_type,
                "label": label,
                "service": service,
                "region": _string(item.get("region")) or _string(params.get("region")),
                "arn": _string(item.get("arn")) or None,
                "tags": item.get("tags") if isinstance(item.get("tags"), dict) else {},
                "attributes": compact_payload(item.get("attributes") if isinstance(item.get("attributes"), dict) else {}),
                "evidence": list(item.get("evidence") or []),
            }
        )
    return {
        "account_id": params.get("account_id"),
        "region": params.get("region"),
        "generated_at": params.get("generated_at"),
        "scope": {"source": "iac_resources", "services_succeeded": sorted({_string(node.get("service")) for node in nodes})},
        "nodes": nodes,
        "edges": [],
        "warnings": warnings,
    }


def _expected_snapshot(params: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    snapshot = _snapshot_from_params(params, "iac_snapshot", "expected_snapshot", "expected_topology_snapshot")
    if snapshot is not None:
        return snapshot, [], "snapshot"
    resources = params.get("iac_resources")
    if isinstance(resources, list):
        expected = _expected_snapshot_from_resources(resources, params)
        return expected, list(expected.get("warnings") or []), "iac_resources"
    return None, [{"severity": "warning", "message": "No IaC snapshot or iac_resources were supplied."}], "missing"


def _drift_kind(change_type: str, item_kind: str) -> str:
    if item_kind == "edge":
        return {
            "added": "unmanaged_relationship",
            "removed": "missing_relationship",
            "changed": "relationship_drift",
        }.get(change_type, "relationship_drift")
    return {
        "added": "unmanaged_runtime",
        "removed": "missing_runtime",
        "changed": "configuration_drift",
    }.get(change_type, "configuration_drift")


def _drift_severity(diff: dict[str, Any], item_kind: str) -> str:
    if item_kind == "edge":
        return str(diff.get("severity") or "medium")
    node_type = str(diff.get("type") or "")
    change_type = str(diff.get("change_type") or "")
    if node_type in HIGH_IMPACT_TYPES and change_type in {"removed", "changed"}:
        return "high"
    if node_type in HIGH_IMPACT_TYPES:
        return "medium"
    return str(diff.get("severity") or "low")


def _drift_item(diff: dict[str, Any], *, item_kind: str) -> dict[str, Any]:
    change_type = str(diff.get("change_type") or "")
    drift_kind = _drift_kind(change_type, item_kind)
    return {
        "drift_kind": drift_kind,
        "change_type": change_type,
        "item_kind": item_kind,
        "id": diff.get("id") or diff.get("key"),
        "type": diff.get("type"),
        "service": diff.get("service"),
        "severity": _drift_severity(diff, item_kind),
        "changed_fields": list(diff.get("changed_fields") or []),
        "expected": diff.get("before") if change_type in {"changed", "removed"} else None,
        "runtime": diff.get("after") if change_type in {"changed", "added"} else None,
        "evidence": diff.get("evidence") or {},
    }


def _summarize_drift(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for item in items:
        by_kind[str(item.get("drift_kind"))] = by_kind.get(str(item.get("drift_kind")), 0) + 1
        by_severity[str(item.get("severity"))] = by_severity.get(str(item.get("severity")), 0) + 1
    return {
        "total_drift_items": len(items),
        "by_kind": by_kind,
        "by_severity": by_severity,
        "has_high_severity": by_severity.get("high", 0) > 0,
    }


async def build_runtime_vs_iac_drift(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    expected, warnings, expected_source = _expected_snapshot(params)
    if expected is None:
        return {
            "status": "invalid_input",
            "error": "iac_snapshot, expected_snapshot or iac_resources is required",
            "warnings": warnings,
        }

    runtime = _snapshot_from_params(params, "runtime_snapshot", "candidate_snapshot", "current_snapshot")
    runtime_source = "provided"
    if runtime is None:
        snapshot_params = params.get("snapshot_params") if isinstance(params.get("snapshot_params"), dict) else {}
        runtime = await build_aws_topology_snapshot(context, snapshot_params)
        runtime_source = "collected"

    diff = compare_aws_topology_snapshots(expected, runtime)
    drift_items = [
        *[_drift_item(item, item_kind="node") for item in diff.get("node_diffs", [])],
        *[_drift_item(item, item_kind="edge") for item in diff.get("edge_diffs", [])],
    ]
    return {
        "status": "ok",
        "expected_source": expected_source,
        "runtime_source": runtime_source,
        "expected": diff.get("baseline"),
        "runtime": diff.get("candidate"),
        "summary": _summarize_drift(drift_items),
        "service_summary": diff.get("service_summary") or {},
        "drift_items": drift_items,
        "warnings": [*warnings, *(diff.get("warnings") or [])],
    }


class AwsRuntimeVsIacDriftTool:
    name = "aws_runtime_vs_iac_drift"
    description = (
        "Compare expected IaC topology against live AWS runtime topology and report missing, unmanaged and changed "
        "resources or relationships with severity and evidence."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_runtime_vs_iac_drift(context, params or {})
