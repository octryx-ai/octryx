"""EKS cluster and node group collectors for the AWS topology graph."""

from __future__ import annotations

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, evidence, node_id, safe_aws_call
from .aws_topology_services import link_vpc_config
from .common import _string


async def discover_eks(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "eks", ["list-clusters"])) or {}
    for name in (data.get("clusters") or [])[:max_items]:
        detail = (await safe_aws_call(context, builder, "eks", ["describe-cluster", "--name", str(name)])) or {}
        cluster = detail.get("cluster") or {}
        cluster_name = _string(cluster.get("name") or name)
        if not cluster_name:
            continue
        arn = _string(cluster.get("arn")) or None
        item_id = node_id("eks_cluster", arn or cluster_name)
        vpc_config = cluster.get("resourcesVpcConfig") or {}
        builder.add_node(
            item_id,
            node_type="eks_cluster",
            label=cluster_name,
            service="eks",
            region=region,
            arn=arn,
            tags=cluster.get("tags") if isinstance(cluster.get("tags"), dict) else {},
            attributes={
                "status": cluster.get("status"),
                "version": cluster.get("version"),
                "endpoint_public_access": vpc_config.get("endpointPublicAccess"),
                "endpoint_private_access": vpc_config.get("endpointPrivateAccess"),
                "vpc_id": vpc_config.get("vpcId"),
            },
            evidence_items=[evidence("eks", "describe-cluster", f"cluster[{cluster_name}]")],
        )
        link_vpc_config(builder, item_id, "eks", "describe-cluster", f"cluster[{cluster_name}]", vpc_config)
        await _discover_eks_nodegroups(
            context,
            builder,
            region=region,
            cluster_name=cluster_name,
            cluster_node_id=item_id,
            max_items=max_items,
        )


async def _discover_eks_nodegroups(
    context: ToolContext,
    builder: TopologyBuilder,
    *,
    region: str,
    cluster_name: str,
    cluster_node_id: str,
    max_items: int,
) -> None:
    data = (
        await safe_aws_call(
            context,
            builder,
            "eks",
            ["list-nodegroups", "--cluster-name", cluster_name],
        )
    ) or {}
    for name in (data.get("nodegroups") or [])[:max_items]:
        detail = (
            await safe_aws_call(
                context,
                builder,
                "eks",
                ["describe-nodegroup", "--cluster-name", cluster_name, "--nodegroup-name", str(name)],
            )
        ) or {}
        nodegroup = detail.get("nodegroup") or {}
        nodegroup_name = _string(nodegroup.get("nodegroupName") or name)
        if not nodegroup_name:
            continue
        item_id = _add_nodegroup_node(builder, nodegroup, region=region, cluster_name=cluster_name, name=nodegroup_name)
        path = f"nodegroup[{cluster_name}/{nodegroup_name}]"
        _link_nodegroup(builder, nodegroup, item_id, cluster_node_id=cluster_node_id, path=path)
        _add_nodegroup_autoscaling_groups(
            builder, nodegroup, item_id, region=region, cluster_name=cluster_name, nodegroup_name=nodegroup_name
        )


def _add_nodegroup_node(
    builder: TopologyBuilder,
    nodegroup: dict,
    *,
    region: str,
    cluster_name: str,
    name: str,
) -> str:
    arn = _string(nodegroup.get("nodegroupArn")) or None
    item_id = node_id("eks_nodegroup", arn or f"{cluster_name}:{name}")
    scaling = nodegroup.get("scalingConfig") or {}
    builder.add_node(
        item_id,
        node_type="eks_nodegroup",
        label=name,
        service="eks",
        region=region,
        arn=arn,
        tags=nodegroup.get("tags") if isinstance(nodegroup.get("tags"), dict) else {},
        attributes={
            "cluster_name": cluster_name,
            "status": nodegroup.get("status"),
            "ami_type": nodegroup.get("amiType"),
            "capacity_type": nodegroup.get("capacityType"),
            "instance_types": nodegroup.get("instanceTypes"),
            "desired_size": scaling.get("desiredSize"),
            "min_size": scaling.get("minSize"),
            "max_size": scaling.get("maxSize"),
        },
        evidence_items=[evidence("eks", "describe-nodegroup", f"nodegroup[{cluster_name}/{name}]")],
    )
    return item_id


def _link_nodegroup(
    builder: TopologyBuilder,
    nodegroup: dict,
    item_id: str,
    *,
    cluster_node_id: str,
    path: str,
) -> None:
    builder.add_edge(
        item_id,
        cluster_node_id,
        "belongs_to",
        service="eks",
        evidence_items=[evidence("eks", "describe-nodegroup", f"{path}.clusterName")],
    )
    for subnet_id in nodegroup.get("subnets") or []:
        builder.add_edge(
            item_id,
            node_id("subnet", subnet_id),
            "uses_subnet",
            service="eks",
            evidence_items=[evidence("eks", "describe-nodegroup", f"{path}.subnets")],
        )
    remote_group = _string((nodegroup.get("resources") or {}).get("remoteAccessSecurityGroup"))
    if remote_group:
        builder.add_edge(
            item_id,
            node_id("security_group", remote_group),
            "uses_security_group",
            service="eks",
            evidence_items=[evidence("eks", "describe-nodegroup", f"{path}.remoteAccessSecurityGroup")],
        )


def _add_nodegroup_autoscaling_groups(
    builder: TopologyBuilder,
    nodegroup: dict,
    item_id: str,
    *,
    region: str,
    cluster_name: str,
    nodegroup_name: str,
) -> None:
    path = f"nodegroup[{cluster_name}/{nodegroup_name}].autoScalingGroups"
    for asg in (nodegroup.get("resources") or {}).get("autoScalingGroups") or []:
        asg_name = _string(asg.get("name"))
        if not asg_name:
            continue
        asg_id = node_id("autoscaling_group", asg_name)
        builder.add_node(
            asg_id,
            node_type="autoscaling_group",
            label=asg_name,
            service="eks",
            region=region,
            attributes={"cluster_name": cluster_name, "nodegroup_name": nodegroup_name},
            evidence_items=[evidence("eks", "describe-nodegroup", path)],
        )
        builder.add_edge(
            asg_id,
            item_id,
            "backs",
            service="eks",
            evidence_items=[evidence("eks", "describe-nodegroup", path)],
        )
