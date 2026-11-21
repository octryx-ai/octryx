"""Security group rule edges for the AWS topology graph."""

from __future__ import annotations

from .aws_topology_common import TopologyBuilder, evidence, node_id
from .common import _string


def add_security_group_rules(
    builder: TopologyBuilder,
    group: dict,
    group_id: str,
    group_node_id: str,
    region: str,
) -> None:
    _add_security_group_permissions(
        builder,
        permissions=group.get("IpPermissions") or [],
        group_id=group_id,
        group_node_id=group_node_id,
        region=region,
        edge_type="allows_ingress_to",
        direction="ingress",
    )
    _add_security_group_permissions(
        builder,
        permissions=group.get("IpPermissionsEgress") or [],
        group_id=group_id,
        group_node_id=group_node_id,
        region=region,
        edge_type="allows_egress_to",
        direction="egress",
    )


def _add_security_group_permissions(
    builder: TopologyBuilder,
    *,
    permissions: list[dict],
    group_id: str,
    group_node_id: str,
    region: str,
    edge_type: str,
    direction: str,
) -> None:
    source_path = "IpPermissions" if direction == "ingress" else "IpPermissionsEgress"
    for permission in permissions:
        _add_cidr_permission_edges(
            builder,
            permission=permission,
            group_id=group_id,
            group_node_id=group_node_id,
            region=region,
            edge_type=edge_type,
            direction=direction,
            source_path=source_path,
        )
        _add_security_group_pair_edges(
            builder,
            permission=permission,
            group_id=group_id,
            group_node_id=group_node_id,
            region=region,
            edge_type=edge_type,
            direction=direction,
            source_path=source_path,
        )


def _add_cidr_permission_edges(
    builder: TopologyBuilder,
    *,
    permission: dict,
    group_id: str,
    group_node_id: str,
    region: str,
    edge_type: str,
    direction: str,
    source_path: str,
) -> None:
    ranges = [
        *(
            ("cidr", _string(item.get("CidrIp")), item.get("Description"))
            for item in permission.get("IpRanges") or []
        ),
        *(
            ("cidr", _string(item.get("CidrIpv6")), item.get("Description"))
            for item in permission.get("Ipv6Ranges") or []
        ),
    ]
    for target_type, cidr, description in ranges:
        if not cidr:
            continue
        cidr_node = node_id("cidr", cidr)
        builder.add_node(
            cidr_node,
            node_type="cidr",
            label=cidr,
            service="ec2",
            region=region,
            attributes={"description": description},
            evidence_items=[evidence("ec2", "describe-security-groups", f"SecurityGroups[{group_id}].{source_path}")],
        )
        source, target = (cidr_node, group_node_id) if direction == "ingress" else (group_node_id, cidr_node)
        builder.add_edge(
            source,
            target,
            edge_type,
            service="ec2",
            attributes={
                **_permission_edge_attributes(permission),
                "source_type" if direction == "ingress" else "target_type": target_type,
                "source_description" if direction == "ingress" else "target_description": description,
            },
            evidence_items=[evidence("ec2", "describe-security-groups", f"SecurityGroups[{group_id}].{source_path}")],
        )


def _add_security_group_pair_edges(
    builder: TopologyBuilder,
    *,
    permission: dict,
    group_id: str,
    group_node_id: str,
    region: str,
    edge_type: str,
    direction: str,
    source_path: str,
) -> None:
    for pair in permission.get("UserIdGroupPairs") or []:
        peer_group_id = _string(pair.get("GroupId"))
        if not peer_group_id:
            continue
        peer_node_id = node_id("security_group", peer_group_id)
        builder.add_node(
            peer_node_id,
            node_type="security_group",
            label=_string(pair.get("GroupName")) or peer_group_id,
            service="ec2",
            region=region,
            attributes={
                "group_id": peer_group_id,
                "vpc_id": pair.get("VpcId"),
                "referenced_by_security_group_rule": True,
            },
            evidence_items=[evidence("ec2", "describe-security-groups", f"SecurityGroups[{group_id}].{source_path}")],
        )
        source, target = (peer_node_id, group_node_id) if direction == "ingress" else (group_node_id, peer_node_id)
        builder.add_edge(
            source,
            target,
            edge_type,
            service="ec2",
            attributes={
                **_permission_edge_attributes(permission),
                "source_type" if direction == "ingress" else "target_type": "security_group",
            },
            evidence_items=[evidence("ec2", "describe-security-groups", f"SecurityGroups[{group_id}].{source_path}")],
        )


def _permission_edge_attributes(permission: dict) -> dict:
    return {
        "protocol": permission.get("IpProtocol"),
        "from_port": permission.get("FromPort"),
        "to_port": permission.get("ToPort"),
    }
