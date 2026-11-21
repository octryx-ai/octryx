"""AWS topology overview connector tool."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from ...services.tool_result_compression.strategy_aws import build_aws_topology_diagram_brief
from ...time_utils import utc_now
from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, bounded_int, evidence, node_id, requested_services, safe_aws_call
from .aws_topology_deep_edges import collect_deep_edges
from .aws_topology_flow_edges import derive_flow_edges
from .aws_topology_region_services import discover_region_services
from .aws_topology_summary import build_topology_service_summary
from .common import _string


def _region(context: ToolContext) -> str:
    return (
        _string(context.project_config.get("aws_region"))
        or os.environ.get("AWS_REGION", "")
        or os.environ.get("AWS_DEFAULT_REGION", "")
    )


# Global AWS APIs return the same data regardless of client region; calling
# them once per snapshot avoids duplicate work (the builder would dedupe the
# nodes anyway).
_GLOBAL_SERVICES = {"s3", "cloudfront", "route53"}
_MAX_REGIONS = 4


def _requested_regions(context: ToolContext, params: dict[str, Any]) -> list[str]:
    """Explicit `regions` param (bounded, deduplicated, order-preserving);
    defaults to the configured region."""
    raw = params.get("regions")
    regions: list[str] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            value = _string(item)
            if value and value not in regions:
                regions.append(value)
    if not regions:
        default = _region(context)
        regions = [default] if default else []
    return regions[:_MAX_REGIONS]


def _context_for_region(context: ToolContext, region: str) -> ToolContext:
    """Shallow context clone pinned to one region; the boto session reads
    `project_config['aws_region']`, so this is the only override needed."""
    if _string(context.project_config.get("aws_region")) == region:
        return context
    return replace(context, project_config={**context.project_config, "aws_region": region})


def _add_account_node(builder: TopologyBuilder, identity: dict[str, Any], region: str) -> str | None:
    account_id = _string(identity.get("Account"))
    if not account_id:
        return None
    item_id = node_id("aws_account", account_id)
    builder.add_node(
        item_id,
        node_type="aws_account",
        label=account_id,
        service="sts",
        region=region,
        arn=_string(identity.get("Arn")) or None,
        attributes={"user_id": identity.get("UserId")},
        evidence_items=[evidence("sts", "get-caller-identity", "Account")],
    )
    return item_id


async def _scan_regions(
    context: ToolContext,
    builder: TopologyBuilder,
    services: list[str],
    *,
    regions: list[str],
    max_items: int,
    params: dict[str, Any],
) -> None:
    for index, snapshot_region in enumerate(regions):
        region_services = set(services) if index == 0 else set(services) - _GLOBAL_SERVICES
        region_context = _context_for_region(context, snapshot_region)
        await discover_region_services(
            region_context,
            builder,
            region_services,
            region=snapshot_region,
            max_items=max_items,
            params=params,
        )
        await collect_deep_edges(
            region_context,
            builder,
            region=snapshot_region,
            max_items=max_items,
            services=region_services,
            include_global=index == 0,
        )


def _snapshot_scope(
    context: ToolContext,
    builder: TopologyBuilder,
    params: dict[str, Any],
    *,
    regions: list[str],
    services: list[str],
    max_items: int,
    max_nodes: int,
) -> dict[str, Any]:
    return {
        "project_ids": list(context.project_ids or []),
        "regions": regions,
        "services_requested": services,
        "services_succeeded": sorted(builder.services_succeeded),
        "services_failed": sorted(builder.services_failed),
        "services_skipped": sorted(builder.services_skipped),
        "max_items": max_items,
        "max_nodes": max_nodes,
        "diagram_brief_requested": bool(params.get("diagram_brief")),
        "diagram_detail": _diagram_detail(params),
    }


async def build_aws_topology_snapshot(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    regions = _requested_regions(context, params)
    region = regions[0] if regions else _region(context)
    services = requested_services(params)
    # Raising these defaults to full detail made the snapshot exceed the hard result cap: the turn history then
    # only holds a stub without diagram_brief, which silently disables the deterministic diagram pipeline.
    # Keep the bounded defaults; full account totals need a size-safe path.
    max_items = bounded_int(params.get("max_items"), default=25, maximum=1000)
    max_nodes = bounded_int(params.get("max_nodes"), default=300, maximum=5000)
    builder = TopologyBuilder(max_nodes=max_nodes)

    identity = (await safe_aws_call(context, builder, "sts", ["get-caller-identity"])) or {}
    account_id = _string(identity.get("Account"))
    account_node_id = _add_account_node(builder, identity, region)
    await _scan_regions(context, builder, services, regions=regions or [region], max_items=max_items, params=params)

    derive_flow_edges(builder)
    _add_account_edges(builder, account_node_id)
    nodes = list(builder.nodes.values())
    edges = builder.edges
    service_summary = build_topology_service_summary(
        account_id=account_id,
        region=region,
        services_requested=services,
        nodes=nodes,
        edges=edges,
        warnings=builder.warnings,
        services_succeeded=builder.services_succeeded,
        services_failed=builder.services_failed,
        services_skipped=builder.services_skipped,
    )
    result = {
        "account_id": account_id,
        "region": region,
        "generated_at": utc_now().isoformat(),
        "service_summary": service_summary,
        "scope": _snapshot_scope(
            context, builder, params, regions=regions, services=services, max_items=max_items, max_nodes=max_nodes
        ),
        "nodes": nodes,
        "edges": edges,
        "diagram_hints": {
            "suggested_views": ["network", "deployment", "security", "ci_cd"],
            "layout_groups": ["aws_account", "vpc", "subnet", "service"],
        },
        "warnings": builder.warnings,
    }
    if params.get("diagram_brief"):
        result["diagram_brief"] = build_aws_topology_diagram_brief(
            result,
            {
                "diagram_detail": _diagram_detail(params),
                "max_diagram_nodes": params.get("max_diagram_nodes"),
                "max_diagram_edges": params.get("max_diagram_edges"),
            },
        )
    return result


def _diagram_detail(params: dict[str, Any]) -> str:
    detail = _string(params.get("diagram_detail")).lower()
    if detail in {"full", "overview", "complete"}:
        return "full"
    return "compact"


def _add_account_edges(builder: TopologyBuilder, account_node_id: str | None) -> None:
    if not account_node_id:
        return
    for item in list(builder.nodes.values()):
        if item["id"] == account_node_id or item["type"] == "cidr":
            continue
        builder.add_edge(
            item["id"],
            account_node_id,
            "belongs_to_account",
            service=item.get("service") or "aws",
            evidence_items=[evidence("sts", "get-caller-identity", "Account", direct=False)],
        )


class AwsTopologySnapshotTool:
    name = "aws_topology_snapshot"
    description = (
        "Return a bounded, read-only, diagram-ready AWS topology graph with nodes, edges, evidence and warnings. "
        "Use this before drawing AWS architecture diagrams or broad AWS platform overviews."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_aws_topology_snapshot(context, params or {})
