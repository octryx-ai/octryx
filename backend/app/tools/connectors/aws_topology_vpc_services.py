"""VPC-bound AWS topology collectors (EC2 instances, ElastiCache, EFS, ECS, VPC networking extras).

Each one emits ``runs_in``/``uses_subnet``/``uses_security_group`` edges so the renderer nests the resource
into the right subnet tier.
"""

from __future__ import annotations

from ..context import ToolContext
from .aws_topology_common import TopologyBuilder, evidence, safe_aws_call
from .aws_topology_node_links import add_simple_node, link_security_groups, link_subnets, link_vpc
from .common import _string


async def discover_ec2_instances(
    context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int
) -> None:
    data = (await safe_aws_call(context, builder, "ec2", ["describe-instances"])) or {}
    count = 0
    for reservation in data.get("Reservations") or []:
        for inst in reservation.get("Instances") or []:
            if count >= max_items:
                return
            state = (inst.get("State") or {}).get("Name")
            if state in {"terminated", "shutting-down"}:
                continue
            iid = _string(inst.get("InstanceId"))
            if not iid:
                continue
            # EKS/ASG-managed nodes are already represented via nodegroups.
            tags = {t.get("Key"): t.get("Value") for t in (inst.get("Tags") or []) if t.get("Key")}
            if any(k.startswith("eks:") or k == "aws:autoscaling:groupName" for k in tags):
                continue
            count += 1
            label = tags.get("Name") or iid
            item_id = add_simple_node(
                builder, node_type="ec2_instance", identifier=iid, label=label,
                service="ec2", region=region, arn=None, operation="describe-instances",
                attributes={"instance_type": inst.get("InstanceType"), "state": state},
                tags=tags,
            )
            link_vpc(builder, item_id, "ec2", "describe-instances", _string(inst.get("VpcId")))
            link_subnets(builder, item_id, "ec2", "describe-instances", [inst.get("SubnetId")])
            link_security_groups(builder, item_id, "ec2", "describe-instances", inst.get("SecurityGroups"))


async def discover_elasticache(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    # Prefer replication groups (Redis) then standalone clusters.
    groups = (await safe_aws_call(context, builder, "elasticache", ["describe-replication-groups"])) or {}
    seen: set[str] = set()
    for group in (groups.get("ReplicationGroups") or [])[:max_items]:
        gid = _string(group.get("ReplicationGroupId"))
        if not gid:
            continue
        seen.add(gid)
        add_simple_node(
            builder, node_type="elasticache_cluster", identifier=gid, label=gid,
            service="elasticache", region=region, arn=_string(group.get("ARN")) or None,
            operation="describe-replication-groups",
            attributes={"engine": "redis", "status": group.get("Status"),
                        "node_count": len(group.get("MemberClusters") or [])},
        )
    clusters = (await safe_aws_call(context, builder, "elasticache", ["describe-cache-clusters"])) or {}
    for cluster in (clusters.get("CacheClusters") or [])[:max_items]:
        cid = _string(cluster.get("CacheClusterId"))
        if not cid or _string(cluster.get("ReplicationGroupId")) in seen:
            continue
        add_simple_node(
            builder, node_type="elasticache_cluster", identifier=cid, label=cid,
            service="elasticache", region=region, arn=_string(cluster.get("ARN")) or None,
            operation="describe-cache-clusters",
            attributes={"engine": cluster.get("Engine"), "status": cluster.get("CacheClusterStatus"),
                        "node_type": cluster.get("CacheNodeType")},
        )


async def discover_efs(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    data = (await safe_aws_call(context, builder, "efs", ["describe-file-systems"])) or {}
    for fs in (data.get("FileSystems") or [])[:max_items]:
        fsid = _string(fs.get("FileSystemId"))
        if not fsid:
            continue
        label = _string(fs.get("Name")) or fsid
        item_id = add_simple_node(
            builder, node_type="efs_file_system", identifier=fsid, label=label,
            service="efs", region=region, arn=_string(fs.get("FileSystemArn")) or None,
            operation="describe-file-systems",
            attributes={"state": fs.get("LifeCycleState"), "size_bytes": (fs.get("SizeInBytes") or {}).get("Value")},
        )
        mounts = (await safe_aws_call(
            context, builder, "efs", ["describe-mount-targets", "--file-system-id", fsid]
        )) or {}
        subnets = [mt.get("SubnetId") for mt in (mounts.get("MountTargets") or [])]
        link_subnets(builder, item_id, "efs", "describe-mount-targets", subnets)
        vpcs = {_string(mt.get("VpcId")) for mt in (mounts.get("MountTargets") or []) if mt.get("VpcId")}
        if len(vpcs) == 1:
            link_vpc(builder, item_id, "efs", "describe-mount-targets", next(iter(vpcs)))


async def discover_ecs(context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int) -> None:
    clusters = (await safe_aws_call(context, builder, "ecs", ["list-clusters"])) or {}
    for cluster_arn in (clusters.get("clusterArns") or [])[:max_items]:
        carn = _string(cluster_arn)
        if not carn:
            continue
        cname = carn.rsplit("/", 1)[-1]
        cluster_id = add_simple_node(
            builder, node_type="ecs_cluster", identifier=carn, label=cname,
            service="ecs", region=region, arn=carn, operation="list-clusters", attributes={},
        )
        services = (await safe_aws_call(
            context, builder, "ecs", ["list-services", "--cluster", carn]
        )) or {}
        for service_arn in (services.get("serviceArns") or [])[:max_items]:
            sarn = _string(service_arn)
            if not sarn:
                continue
            detail = (await safe_aws_call(
                context, builder, "ecs",
                ["describe-services", "--cluster", carn, "--services", sarn],
            )) or {}
            for svc in detail.get("services") or []:
                sname = _string(svc.get("serviceName")) or sarn.rsplit("/", 1)[-1]
                svc_id = add_simple_node(
                    builder, node_type="ecs_service", identifier=sarn, label=sname,
                    service="ecs", region=region, arn=sarn, operation="describe-services",
                    attributes={"launch_type": svc.get("launchType"),
                                "desired_count": svc.get("desiredCount"),
                                "running_count": svc.get("runningCount")},
                )
                builder.add_edge(
                    svc_id, cluster_id, "belongs_to", service="ecs",
                    evidence_items=[evidence("ecs", "describe-services", "cluster")],
                )
                vpc = (svc.get("networkConfiguration") or {}).get("awsvpcConfiguration") or {}
                link_subnets(builder, svc_id, "ecs", "describe-services", vpc.get("subnets"))
                for gid in vpc.get("securityGroups") or []:
                    link_security_groups(builder, svc_id, "ecs", "describe-services", [gid])


async def discover_networking_extras(
    context: ToolContext, builder: TopologyBuilder, *, region: str, max_items: int
) -> None:
    endpoints = (await safe_aws_call(context, builder, "ec2", ["describe-vpc-endpoints"])) or {}
    for ep in (endpoints.get("VpcEndpoints") or [])[:max_items]:
        eid = _string(ep.get("VpcEndpointId"))
        if not eid:
            continue
        svc = _string(ep.get("ServiceName")).rsplit(".", 1)[-1]
        item_id = add_simple_node(
            builder, node_type="vpc_endpoint", identifier=eid, label=svc or eid,
            service="ec2", region=region, arn=None, operation="describe-vpc-endpoints",
            attributes={"endpoint_type": ep.get("VpcEndpointType"), "state": ep.get("State")},
        )
        link_vpc(builder, item_id, "ec2", "describe-vpc-endpoints", _string(ep.get("VpcId")))
        link_subnets(builder, item_id, "ec2", "describe-vpc-endpoints", ep.get("SubnetIds"))

    peerings = (await safe_aws_call(context, builder, "ec2", ["describe-vpc-peering-connections"])) or {}
    for pc in (peerings.get("VpcPeeringConnections") or [])[:max_items]:
        pid = _string(pc.get("VpcPeeringConnectionId"))
        if not pid:
            continue
        item_id = add_simple_node(
            builder, node_type="vpc_peering", identifier=pid, label=pid,
            service="ec2", region=region, arn=None, operation="describe-vpc-peering-connections",
            attributes={"status": (pc.get("Status") or {}).get("Code")},
        )
        for side in ("RequesterVpcInfo", "AccepterVpcInfo"):
            vpc_id = _string((pc.get(side) or {}).get("VpcId"))
            link_vpc(builder, item_id, "ec2", "describe-vpc-peering-connections", vpc_id)

    tgw = (await safe_aws_call(context, builder, "ec2", ["describe-transit-gateway-attachments"])) or {}
    for att in (tgw.get("TransitGatewayAttachments") or [])[:max_items]:
        tid = _string(att.get("TransitGatewayId"))
        if not tid:
            continue
        item_id = add_simple_node(
            builder, node_type="transit_gateway", identifier=tid, label=tid,
            service="ec2", region=region, arn=None, operation="describe-transit-gateway-attachments",
            attributes={"resource_type": att.get("ResourceType"), "state": att.get("State")},
        )
        link_vpc(builder, item_id, "ec2", "describe-transit-gateway-attachments", _string(att.get("ResourceId")))
