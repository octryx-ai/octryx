"""RDS instance and proxy collectors for the AWS topology graph."""

from __future__ import annotations

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, evidence, node_id, safe_aws_call
from .common import _string


async def discover_rds(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "rds", ["describe-db-instances"])) or {}
    for item in (data.get("DBInstances") or [])[:max_items]:
        identifier = _string(item.get("DBInstanceIdentifier"))
        if not identifier:
            continue
        arn = _string(item.get("DBInstanceArn")) or None
        item_id = node_id("rds_instance", arn or identifier)
        subnet_group = item.get("DBSubnetGroup") or {}
        builder.add_node(
            item_id,
            node_type="rds_instance",
            label=identifier,
            service="rds",
            region=region,
            arn=arn,
            attributes={
                "engine": item.get("Engine"),
                "status": item.get("DBInstanceStatus"),
                "class": item.get("DBInstanceClass"),
                "multi_az": item.get("MultiAZ"),
                "publicly_accessible": item.get("PubliclyAccessible"),
                "vpc_id": subnet_group.get("VpcId"),
            },
            evidence_items=[evidence("rds", "describe-db-instances", f"DBInstances[{identifier}]")],
        )
        _link_rds_network(builder, item, item_id, identifier=identifier)
        _add_rds_subnets(builder, subnet_group, item_id, identifier=identifier, region=region)

    await _discover_rds_proxies(context, builder, region=region, max_items=max_items)


def _link_rds_network(builder: TopologyBuilder, item: dict, item_id: str, *, identifier: str) -> None:
    vpc_id = _string((item.get("DBSubnetGroup") or {}).get("VpcId"))
    if vpc_id:
        builder.add_edge(
            item_id,
            node_id("vpc", vpc_id),
            "runs_in",
            service="rds",
            evidence_items=[evidence("rds", "describe-db-instances", f"DBInstances[{identifier}].DBSubnetGroup")],
        )
    for group in item.get("VpcSecurityGroups") or []:
        group_id = _string(group.get("VpcSecurityGroupId"))
        if group_id:
            builder.add_edge(
                item_id,
                node_id("security_group", group_id),
                "uses_security_group",
                service="rds",
                evidence_items=[
                    evidence("rds", "describe-db-instances", f"DBInstances[{identifier}].VpcSecurityGroups")
                ],
            )


def _add_rds_subnets(
    builder: TopologyBuilder,
    subnet_group: dict,
    item_id: str,
    *,
    identifier: str,
    region: str,
) -> None:
    path = f"DBInstances[{identifier}].DBSubnetGroup.Subnets"
    for subnet in subnet_group.get("Subnets") or []:
        subnet_id = _string(subnet.get("SubnetIdentifier"))
        if not subnet_id:
            continue
        builder.add_node(
            node_id("subnet", subnet_id),
            node_type="subnet",
            label=subnet_id,
            service="ec2",
            region=region,
            attributes={"subnet_tier": "db", "subnet_tier_source": "rds_db_subnet_group"},
            evidence_items=[evidence("rds", "describe-db-instances", path)],
        )
        builder.add_edge(
            item_id,
            node_id("subnet", subnet_id),
            "uses_subnet",
            service="rds",
            evidence_items=[evidence("rds", "describe-db-instances", path)],
        )


async def _discover_rds_proxies(
    context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int
) -> None:
    data = (await safe_aws_call(context, builder, "rds", ["describe-db-proxies"])) or {}
    for proxy in (data.get("DBProxies") or [])[:max_items]:
        name = _string(proxy.get("DBProxyName"))
        if not name:
            continue
        item_id = node_id("rds_proxy", _string(proxy.get("DBProxyArn")) or name)
        builder.add_node(
            item_id,
            node_type="rds_proxy",
            label=name,
            service="rds",
            region=region,
            arn=_string(proxy.get("DBProxyArn")) or None,
            attributes={"status": proxy.get("Status"), "engine_family": proxy.get("EngineFamily")},
            evidence_items=[evidence("rds", "describe-db-proxies", f"DBProxies[{name}]")],
        )
        if _string(proxy.get("VpcId")):
            builder.add_edge(
                item_id, node_id("vpc", _string(proxy.get("VpcId"))), "runs_in", service="rds",
                evidence_items=[evidence("rds", "describe-db-proxies", f"DBProxies[{name}].VpcId")],
            )
        for subnet_id in proxy.get("VpcSubnetIds") or []:
            sid = _string(subnet_id)
            if sid:
                builder.add_edge(
                    item_id, node_id("subnet", sid), "uses_subnet", service="rds",
                    evidence_items=[evidence("rds", "describe-db-proxies", f"DBProxies[{name}].VpcSubnetIds")],
                )
