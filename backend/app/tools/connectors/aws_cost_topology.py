"""AWS cost topology report connector tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from ..context import ToolContext
from .aws_core import _aws_json
from .aws_topology import build_aws_topology_snapshot
from .common import _normalize_string_list, _string

MAX_TAG_KEYS = 5
DEFAULT_METRIC = "UnblendedCost"

SERVICE_NAME_MAP: tuple[tuple[str, str], ...] = (
    ("Amazon Elastic Compute Cloud", "ec2"),
    ("Amazon Virtual Private Cloud", "ec2"),
    ("Amazon Relational Database Service", "rds"),
    ("Amazon Elastic Kubernetes Service", "eks"),
    ("Amazon Simple Storage Service", "s3"),
    ("AWS Lambda", "lambda"),
    ("AWS WAF", "wafv2"),
    ("Elastic Load Balancing", "elbv2"),
    ("Amazon Bedrock", "bedrock"),
    ("AWS CodePipeline", "codepipeline"),
    ("Amazon CloudWatch", "cloudwatch"),
)


def _default_start() -> str:
    return datetime.now(UTC).date().replace(day=1).isoformat()


def _default_end() -> str:
    return (datetime.now(UTC).date() + timedelta(days=1)).isoformat()


def _money(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _float_money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001")))


def _topology_nodes(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    nodes = snapshot.get("nodes")
    return [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []


def _mapped_service(cost_service_name: str) -> str | None:
    for needle, service in SERVICE_NAME_MAP:
        if needle.lower() in cost_service_name.lower():
            return service
    normalized = cost_service_name.lower().replace(" ", "_")
    for service in {service for _, service in SERVICE_NAME_MAP}:
        if service in normalized:
            return service
    return None


def _nodes_for_service(nodes: list[dict[str, Any]], service: str) -> list[dict[str, Any]]:
    return [node for node in nodes if _string(node.get("service")) == service]


def _service_cost_rows(data: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    rows = []
    for window in data.get("ResultsByTime") or []:
        period = window.get("TimePeriod") or {}
        for group in window.get("Groups") or []:
            metric_payload = (group.get("Metrics") or {}).get(metric) or {}
            rows.append(
                {
                    "period": period,
                    "service_name": (group.get("Keys") or ["unknown"])[0],
                    "amount": _float_money(_money(metric_payload.get("Amount"))),
                    "unit": metric_payload.get("Unit") or "USD",
                }
            )
    return rows


def _tag_cost_rows(data: dict[str, Any], metric: str, tag_key: str) -> list[dict[str, Any]]:
    rows = []
    for window in data.get("ResultsByTime") or []:
        period = window.get("TimePeriod") or {}
        for group in window.get("Groups") or []:
            metric_payload = (group.get("Metrics") or {}).get(metric) or {}
            rows.append(
                {
                    "period": period,
                    "tag_key": tag_key,
                    "tag_value": (group.get("Keys") or ["untagged"])[0],
                    "amount": _float_money(_money(metric_payload.get("Amount"))),
                    "unit": metric_payload.get("Unit") or "USD",
                }
            )
    return rows


def _service_report(rows: list[dict[str, Any]], nodes: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    service_costs = []
    topology_allocations = []
    unmapped_costs = []
    total = Decimal("0")
    for row in rows:
        amount = _money(row.get("amount"))
        total += amount
        service = _mapped_service(str(row.get("service_name") or ""))
        matched_nodes = _nodes_for_service(nodes, service) if service else []
        cost_item = {
            **row,
            "mapped_topology_service": service,
            "mapped_node_count": len(matched_nodes),
            "allocation_basis": "cost_explorer_service_group",
            "evidence": [{"service": "ce", "operation": "get-cost-and-usage", "metric": metric, "direct": True}],
        }
        service_costs.append(cost_item)
        if not service:
            unmapped_costs.append(cost_item)
            continue
        for node in matched_nodes:
            topology_allocations.append(
                {
                    "node_id": node.get("id"),
                    "node_type": node.get("type"),
                    "label": node.get("label"),
                    "service": service,
                    "service_name": row.get("service_name"),
                    "amount": row.get("amount"),
                    "unit": row.get("unit"),
                    "allocation_basis": "service_level_not_resource_attributed",
                    "evidence": [
                        {"service": "ce", "operation": "get-cost-and-usage", "metric": metric, "direct": True},
                        *list(node.get("evidence") or []),
                    ],
                }
            )
    return {
        "total_amount": _float_money(total),
        "service_costs": service_costs,
        "topology_allocations": topology_allocations,
        "unmapped_costs": unmapped_costs,
    }


async def _cost_by_service(context: ToolContext, *, start: str, end: str, granularity: str, metric: str) -> dict[str, Any]:
    return await _aws_json(
        context,
        "ce",
        [
            "get-cost-and-usage",
            "--time-period",
            f"Start={start},End={end}",
            "--granularity",
            granularity,
            "--metrics",
            metric,
            "--group-by",
            "Type=DIMENSION,Key=SERVICE",
        ],
    )


async def _cost_by_tag(
    context: ToolContext,
    *,
    start: str,
    end: str,
    granularity: str,
    metric: str,
    tag_key: str,
) -> dict[str, Any]:
    return await _aws_json(
        context,
        "ce",
        [
            "get-cost-and-usage",
            "--time-period",
            f"Start={start},End={end}",
            "--granularity",
            granularity,
            "--metrics",
            metric,
            "--group-by",
            f"Type=TAG,Key={tag_key}",
        ],
    )


async def build_aws_cost_topology_report(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    start = _string(params.get("start")) or _default_start()
    end = _string(params.get("end")) or _default_end()
    granularity = (_string(params.get("granularity")) or "MONTHLY").upper()
    metric = _string(params.get("metric")) or DEFAULT_METRIC
    warnings = []

    topology = params.get("topology_snapshot") if isinstance(params.get("topology_snapshot"), dict) else None
    topology_source = "provided" if topology else "missing"
    if topology is None and bool(params.get("collect_topology")):
        snapshot_params = params.get("snapshot_params") if isinstance(params.get("snapshot_params"), dict) else {}
        topology = await build_aws_topology_snapshot(context, snapshot_params)
        topology_source = "collected"

    nodes = _topology_nodes(topology)
    if not nodes:
        warnings.append(
            {
                "severity": "warning",
                "message": "No topology nodes supplied or collected; report will include service costs only.",
            }
        )

    try:
        service_data = await _cost_by_service(context, start=start, end=end, granularity=granularity, metric=metric)
    except Exception as exc:
        return {"status": "error", "error": str(exc), "warnings": warnings}

    service_rows = _service_cost_rows(service_data, metric)
    service_report = _service_report(service_rows, nodes, metric)
    tag_costs = []
    for tag_key in _normalize_string_list(params.get("tag_keys"))[:MAX_TAG_KEYS]:
        try:
            tag_data = await _cost_by_tag(
                context, start=start, end=end, granularity=granularity, metric=metric, tag_key=tag_key
            )
            tag_costs.append({"tag_key": tag_key, "values": _tag_cost_rows(tag_data, metric, tag_key)})
        except Exception as exc:
            warnings.append({"severity": "warning", "message": f"Cost tag query failed for {tag_key}: {exc}"})

    return {
        "status": "ok",
        "period": {"start": start, "end": end, "granularity": granularity},
        "metric": metric,
        "topology_source": topology_source,
        "summary": {
            "total_amount": service_report["total_amount"],
            "service_count": len(service_report["service_costs"]),
            "mapped_topology_allocation_count": len(service_report["topology_allocations"]),
            "unmapped_cost_count": len(service_report["unmapped_costs"]),
        },
        "service_costs": service_report["service_costs"],
        "topology_allocations": service_report["topology_allocations"],
        "tag_costs": tag_costs,
        "unmapped_costs": service_report["unmapped_costs"],
        "warnings": warnings,
    }


class AwsCostTopologyReportTool:
    name = "aws_cost_topology_report"
    description = (
        "Map AWS Cost Explorer service and tag costs onto known topology services without claiming unsupported "
        "resource-level attribution."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_aws_cost_topology_report(context, params or {})
