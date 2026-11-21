"""Elastic Load Balancing collectors for the AWS topology graph."""

from __future__ import annotations

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, evidence, node_id, safe_aws_call
from .common import _string


async def discover_elbv2(
    context: ToolContext,
    builder: TopologyBuilder,
    *,
    region: str,
    max_items: int,
) -> None:
    data = (await safe_aws_call(context, builder, "elbv2", ["describe-load-balancers"])) or {}
    target_group_listeners: dict[str, set[str]] = {}
    for item in (data.get("LoadBalancers") or [])[:max_items]:
        await _add_load_balancer(context, builder, item, region=region, target_group_listeners=target_group_listeners)

    target_groups = (await safe_aws_call(context, builder, "elbv2", ["describe-target-groups"])) or {}
    for item in (target_groups.get("TargetGroups") or [])[:max_items]:
        _add_target_group(builder, item, region=region, target_group_listeners=target_group_listeners)


async def _add_load_balancer(
    context: ToolContext,
    builder: TopologyBuilder,
    item: dict,
    *,
    region: str,
    target_group_listeners: dict[str, set[str]],
) -> None:
    arn = _string(item.get("LoadBalancerArn"))
    name = _string(item.get("LoadBalancerName")) or arn
    if not arn:
        return
    listener_summaries = await _collect_listeners(context, builder, arn, target_group_listeners)
    item_id = node_id("load_balancer", arn)
    builder.add_node(
        item_id,
        node_type="load_balancer",
        label=name,
        service="elbv2",
        region=region,
        arn=arn,
        attributes={
            "dns_name": item.get("DNSName"),
            "scheme": item.get("Scheme"),
            "type": item.get("Type"),
            "state": item.get("State"),
            "vpc_id": item.get("VpcId"),
            **({"listeners": listener_summaries} if listener_summaries else {}),
        },
        evidence_items=[evidence("elbv2", "describe-load-balancers", f"LoadBalancers[{name}]")],
    )
    _link_load_balancer(builder, item, item_id, name)


def _add_target_group(
    builder: TopologyBuilder,
    item: dict,
    *,
    region: str,
    target_group_listeners: dict[str, set[str]],
) -> None:
    arn = _string(item.get("TargetGroupArn"))
    name = _string(item.get("TargetGroupName")) or arn
    if not arn:
        return
    item_id = node_id("target_group", arn)
    builder.add_node(
        item_id,
        node_type="target_group",
        label=name,
        service="elbv2",
        region=region,
        arn=arn,
        attributes={
            "protocol": item.get("Protocol"),
            "port": item.get("Port"),
            "target_type": item.get("TargetType"),
            "vpc_id": item.get("VpcId"),
        },
        evidence_items=[evidence("elbv2", "describe-target-groups", f"TargetGroups[{name}]")],
    )
    listener_summaries = sorted(target_group_listeners.get(arn, set()))
    for lb_arn in item.get("LoadBalancerArns") or []:
        builder.add_edge(
            node_id("load_balancer", lb_arn),
            item_id,
            "routes_to",
            service="elbv2",
            attributes={"listeners": listener_summaries} if listener_summaries else None,
            evidence_items=[evidence("elbv2", "describe-target-groups", f"TargetGroups[{name}].LoadBalancerArns")],
        )


async def _collect_listeners(
    context: ToolContext,
    builder: TopologyBuilder,
    lb_arn: str,
    target_group_listeners: dict[str, set[str]],
) -> list[str]:
    data = (
        await safe_aws_call(
            context, builder, "elbv2", ["describe-listeners", "--load-balancer-arn", lb_arn]
        )
    ) or {}
    summaries: set[str] = set()
    for listener in data.get("Listeners") or []:
        protocol = _string(listener.get("Protocol"))
        port = listener.get("Port")
        if not protocol or port is None:
            continue
        summary = f"{protocol}:{port}"
        summaries.add(summary)
        for action in listener.get("DefaultActions") or []:
            forwarded = [_string(action.get("TargetGroupArn"))]
            forwarded.extend(
                _string(entry.get("TargetGroupArn"))
                for entry in ((action.get("ForwardConfig") or {}).get("TargetGroups") or [])
            )
            for target_group_arn in forwarded:
                if target_group_arn:
                    target_group_listeners.setdefault(target_group_arn, set()).add(summary)
    return sorted(summaries)


def _link_load_balancer(builder: TopologyBuilder, item: dict, item_id: str, name: str) -> None:
    vpc_id = _string(item.get("VpcId"))
    if vpc_id:
        builder.add_edge(
            item_id,
            node_id("vpc", vpc_id),
            "runs_in",
            service="elbv2",
            evidence_items=[evidence("elbv2", "describe-load-balancers", f"LoadBalancers[{name}].VpcId")],
        )
    for zone in item.get("AvailabilityZones") or []:
        subnet_id = _string(zone.get("SubnetId"))
        if subnet_id:
            builder.add_edge(
                item_id,
                node_id("subnet", subnet_id),
                "uses_subnet",
                service="elbv2",
                evidence_items=[
                    evidence("elbv2", "describe-load-balancers", f"LoadBalancers[{name}].AvailabilityZones")
                ],
            )
    for group_id in item.get("SecurityGroups") or []:
        builder.add_edge(
            item_id,
            node_id("security_group", group_id),
            "uses_security_group",
            service="elbv2",
            evidence_items=[evidence("elbv2", "describe-load-balancers", f"LoadBalancers[{name}].SecurityGroups")],
        )
