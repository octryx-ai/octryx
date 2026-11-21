"""Gateway and route table collectors for the AWS topology graph."""

from __future__ import annotations

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, evidence, node_id, safe_aws_call, tags_from_aws_list
from .common import _string


async def discover_ec2_routing(
    context: ToolContext,
    builder: TopologyBuilder,
    *,
    region: str,
    max_items: int,
) -> None:
    internet_gateways = (await safe_aws_call(context, builder, "ec2", ["describe-internet-gateways"])) or {}
    for item in (internet_gateways.get("InternetGateways") or [])[:max_items]:
        _add_internet_gateway(builder, item, region)

    nat_gateways = (await safe_aws_call(context, builder, "ec2", ["describe-nat-gateways"])) or {}
    for item in (nat_gateways.get("NatGateways") or [])[:max_items]:
        _add_nat_gateway(builder, item, region)

    route_tables = (await safe_aws_call(context, builder, "ec2", ["describe-route-tables"])) or {}
    for item in (route_tables.get("RouteTables") or [])[:max_items]:
        _add_route_table(builder, item, region)


def _add_internet_gateway(builder: TopologyBuilder, item: dict, region: str) -> None:
    gateway_id = _string(item.get("InternetGatewayId"))
    if not gateway_id:
        return
    item_id = node_id("internet_gateway", gateway_id)
    builder.add_node(
        item_id,
        node_type="internet_gateway",
        label=gateway_id,
        service="ec2",
        region=region,
        tags=tags_from_aws_list(item.get("Tags")),
        attributes={"state": (item.get("Attachments") or [{}])[0].get("State")},
        evidence_items=[evidence("ec2", "describe-internet-gateways", f"InternetGateways[{gateway_id}]")],
    )
    for attachment in item.get("Attachments") or []:
        vpc_id = _string(attachment.get("VpcId"))
        if vpc_id:
            builder.add_edge(
                item_id,
                node_id("vpc", vpc_id),
                "attached_to",
                service="ec2",
                evidence_items=[
                    evidence("ec2", "describe-internet-gateways", f"InternetGateways[{gateway_id}].Attachments")
                ],
            )


def _add_nat_gateway(builder: TopologyBuilder, item: dict, region: str) -> None:
    gateway_id = _string(item.get("NatGatewayId"))
    if not gateway_id:
        return
    item_id = node_id("nat_gateway", gateway_id)
    subnet_id = _string(item.get("SubnetId"))
    vpc_id = _string(item.get("VpcId"))
    builder.add_node(
        item_id,
        node_type="nat_gateway",
        label=gateway_id,
        service="ec2",
        region=region,
        tags=tags_from_aws_list(item.get("Tags")),
        attributes={"state": item.get("State"), "subnet_id": subnet_id, "vpc_id": vpc_id},
        evidence_items=[evidence("ec2", "describe-nat-gateways", f"NatGateways[{gateway_id}]")],
    )
    if subnet_id:
        builder.add_edge(
            item_id,
            node_id("subnet", subnet_id),
            "runs_in",
            service="ec2",
            evidence_items=[evidence("ec2", "describe-nat-gateways", f"NatGateways[{gateway_id}].SubnetId")],
        )
    if vpc_id:
        builder.add_edge(
            item_id,
            node_id("vpc", vpc_id),
            "runs_in",
            service="ec2",
            evidence_items=[evidence("ec2", "describe-nat-gateways", f"NatGateways[{gateway_id}].VpcId")],
        )


def _add_route_table(builder: TopologyBuilder, item: dict, region: str) -> None:
    route_table_id = _string(item.get("RouteTableId"))
    vpc_id = _string(item.get("VpcId"))
    if not route_table_id:
        return
    route_table_node_id = node_id("route_table", route_table_id)
    builder.add_node(
        route_table_node_id,
        node_type="route_table",
        label=route_table_id,
        service="ec2",
        region=region,
        tags=tags_from_aws_list(item.get("Tags")),
        attributes={"vpc_id": vpc_id, "is_main": _route_table_is_main(item)},
        evidence_items=[evidence("ec2", "describe-route-tables", f"RouteTables[{route_table_id}]")],
    )
    if vpc_id:
        builder.add_edge(
            route_table_node_id,
            node_id("vpc", vpc_id),
            "belongs_to",
            service="ec2",
            evidence_items=[evidence("ec2", "describe-route-tables", f"RouteTables[{route_table_id}].VpcId")],
        )
    _link_route_targets(builder, item, route_table_node_id, route_table_id)
    _classify_associated_subnets(builder, item, route_table_node_id, route_table_id, region)


def _route_table_is_main(route_table: dict) -> bool:
    return any(bool(association.get("Main")) for association in route_table.get("Associations") or [])


def _default_route_target_type(route_table: dict) -> str:
    for route in route_table.get("Routes") or []:
        destination = _string(route.get("DestinationCidrBlock") or route.get("DestinationIpv6CidrBlock"))
        if destination not in {"0.0.0.0/0", "::/0"}:
            continue
        gateway_id = _string(route.get("GatewayId"))
        nat_gateway_id = _string(route.get("NatGatewayId"))
        if gateway_id.startswith("igw-"):
            return "internet_gateway"
        if nat_gateway_id.startswith("nat-"):
            return "nat_gateway"
    return ""


def _link_route_targets(
    builder: TopologyBuilder,
    route_table: dict,
    route_table_node_id: str,
    route_table_id: str,
) -> None:
    for route in route_table.get("Routes") or []:
        destination = _string(route.get("DestinationCidrBlock") or route.get("DestinationIpv6CidrBlock"))
        if destination not in {"0.0.0.0/0", "::/0"}:
            continue
        gateway_id = _string(route.get("GatewayId"))
        nat_gateway_id = _string(route.get("NatGatewayId"))
        target_node_id = ""
        if gateway_id.startswith("igw-"):
            target_node_id = node_id("internet_gateway", gateway_id)
        elif nat_gateway_id.startswith("nat-"):
            target_node_id = node_id("nat_gateway", nat_gateway_id)
        if target_node_id:
            builder.add_edge(
                route_table_node_id,
                target_node_id,
                "routes_to",
                service="ec2",
                evidence_items=[evidence("ec2", "describe-route-tables", f"RouteTables[{route_table_id}].Routes")],
                attributes={"destination": destination},
            )


def _classify_associated_subnets(
    builder: TopologyBuilder,
    route_table: dict,
    route_table_node_id: str,
    route_table_id: str,
    region: str,
) -> None:
    target_type = _default_route_target_type(route_table)
    subnet_tier = "public" if target_type == "internet_gateway" else "private"
    subnet_tier_source = (
        "route_table_default_route"
        if target_type in {"internet_gateway", "nat_gateway"}
        else "route_table_no_public_default_route"
    )
    for association in route_table.get("Associations") or []:
        subnet_id = _string(association.get("SubnetId"))
        if not subnet_id:
            continue
        attrs = {"route_table_id": route_table_id}
        if subnet_tier:
            attrs["subnet_tier"] = subnet_tier
            attrs["subnet_tier_source"] = subnet_tier_source
        builder.add_node(
            node_id("subnet", subnet_id),
            node_type="subnet",
            label=subnet_id,
            service="ec2",
            region=region,
            attributes=attrs,
            evidence_items=[evidence("ec2", "describe-route-tables", f"RouteTables[{route_table_id}].Associations")],
        )
        builder.add_edge(
            node_id("subnet", subnet_id),
            route_table_node_id,
            "uses_route_table",
            service="ec2",
            evidence_items=[evidence("ec2", "describe-route-tables", f"RouteTables[{route_table_id}].Associations")],
        )
