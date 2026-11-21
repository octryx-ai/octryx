"""VPC, subnet and security group collectors for the AWS topology graph."""

from __future__ import annotations

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, evidence, node_id, safe_aws_call, tags_from_aws_list
from .aws_topology_routing import discover_ec2_routing
from .aws_topology_security_groups import add_security_group_rules
from .common import _string


async def discover_ec2_network(
    context: ToolContext,
    builder: TopologyBuilder,
    *,
    region: str,
    max_items: int,
) -> None:
    vpcs = (await safe_aws_call(context, builder, "ec2", ["describe-vpcs"])) or {}
    for item in (vpcs.get("Vpcs") or [])[:max_items]:
        _add_vpc(builder, item, region)

    subnets = (await safe_aws_call(context, builder, "ec2", ["describe-subnets"])) or {}
    for item in (subnets.get("Subnets") or [])[:max_items]:
        _add_subnet(builder, item, region)

    groups = (await safe_aws_call(context, builder, "ec2", ["describe-security-groups"])) or {}
    for item in (groups.get("SecurityGroups") or [])[:max_items]:
        _add_security_group(builder, item, region)

    await discover_ec2_routing(context, builder, region=region, max_items=max_items)


def _add_vpc(builder: TopologyBuilder, item: dict, region: str) -> None:
    vpc_id = _string(item.get("VpcId"))
    if not vpc_id:
        return
    builder.add_node(
        node_id("vpc", vpc_id),
        node_type="vpc",
        label=vpc_id,
        service="ec2",
        region=region,
        tags=tags_from_aws_list(item.get("Tags")),
        attributes={
            "cidr_block": item.get("CidrBlock"),
            "state": item.get("State"),
            "is_default": item.get("IsDefault"),
        },
        evidence_items=[evidence("ec2", "describe-vpcs", f"Vpcs[{vpc_id}]")],
    )


def _add_subnet(builder: TopologyBuilder, item: dict, region: str) -> None:
    subnet_id = _string(item.get("SubnetId"))
    vpc_id = _string(item.get("VpcId"))
    if not subnet_id:
        return
    item_id = node_id("subnet", subnet_id)
    builder.add_node(
        item_id,
        node_type="subnet",
        label=subnet_id,
        service="ec2",
        region=region,
        tags=tags_from_aws_list(item.get("Tags")),
        attributes={
            "vpc_id": vpc_id,
            "availability_zone": item.get("AvailabilityZone"),
            "cidr_block": item.get("CidrBlock"),
            "map_public_ip_on_launch": item.get("MapPublicIpOnLaunch"),
            **_subnet_public_ip_tier_attrs(item),
        },
        evidence_items=[evidence("ec2", "describe-subnets", f"Subnets[{subnet_id}]")],
    )
    if vpc_id:
        builder.add_edge(
            item_id,
            node_id("vpc", vpc_id),
            "belongs_to",
            service="ec2",
            evidence_items=[evidence("ec2", "describe-subnets", f"Subnets[{subnet_id}].VpcId")],
        )


def _add_security_group(builder: TopologyBuilder, item: dict, region: str) -> None:
    group_id = _string(item.get("GroupId"))
    vpc_id = _string(item.get("VpcId"))
    if not group_id:
        return
    item_id = node_id("security_group", group_id)
    builder.add_node(
        item_id,
        node_type="security_group",
        label=_string(item.get("GroupName")) or group_id,
        service="ec2",
        region=region,
        tags=tags_from_aws_list(item.get("Tags")),
        attributes={"group_id": group_id, "vpc_id": vpc_id, "description": item.get("Description")},
        evidence_items=[evidence("ec2", "describe-security-groups", f"SecurityGroups[{group_id}]")],
    )
    if vpc_id:
        builder.add_edge(
            item_id,
            node_id("vpc", vpc_id),
            "attached_to",
            service="ec2",
            evidence_items=[evidence("ec2", "describe-security-groups", f"SecurityGroups[{group_id}].VpcId")],
        )
    add_security_group_rules(builder, item, group_id, item_id, region)


def _subnet_public_ip_tier_attrs(subnet: dict) -> dict[str, str]:
    if subnet.get("MapPublicIpOnLaunch") is True:
        return {"subnet_tier": "public", "subnet_tier_source": "subnet_map_public_ip_on_launch"}
    return {}
