"""Node and VPC placement helpers shared by the extended AWS topology collectors."""

from __future__ import annotations

from typing import Any

from .aws_topology_common import TopologyBuilder, evidence, node_id
from .common import _string


def add_simple_node(
    builder: TopologyBuilder,
    *,
    node_type: str,
    identifier: str,
    label: str,
    service: str,
    region: str,
    arn: str | None,
    operation: str,
    attributes: dict[str, Any] | None = None,
    tags: dict[str, str] | None = None,
) -> str:
    item_id = node_id(node_type, arn or identifier)
    builder.add_node(
        item_id,
        node_type=node_type,
        label=label,
        service=service,
        region=region,
        arn=arn,
        tags=tags or {},
        attributes=attributes or {},
        evidence_items=[evidence(service, operation, f"{node_type}[{label}]")],
    )
    return item_id


def link_vpc(builder: TopologyBuilder, item_id: str, service: str, operation: str, vpc_id: str) -> None:
    if vpc_id:
        builder.add_edge(
            item_id,
            node_id("vpc", vpc_id),
            "runs_in",
            service=service,
            evidence_items=[evidence(service, operation, "VpcId")],
        )


def link_subnets(
    builder: TopologyBuilder,
    item_id: str,
    service: str,
    operation: str,
    subnet_ids: Any,
) -> None:
    for subnet_id in subnet_ids or []:
        sid = _string(subnet_id)
        if sid:
            builder.add_edge(
                item_id,
                node_id("subnet", sid),
                "uses_subnet",
                service=service,
                evidence_items=[evidence(service, operation, "SubnetIds")],
            )


def link_security_groups(
    builder: TopologyBuilder,
    item_id: str,
    service: str,
    operation: str,
    group_ids: Any,
) -> None:
    for group in group_ids or []:
        gid = _string(group.get("GroupId") if isinstance(group, dict) else group)
        if gid:
            builder.add_edge(
                item_id,
                node_id("security_group", gid),
                "uses_security_group",
                service=service,
                evidence_items=[evidence(service, operation, "SecurityGroups")],
            )
