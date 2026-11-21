"""Derive high-level traffic-flow edges from the collected topology.

The raw AWS evidence expresses connectivity indirectly: load balancers point at
IP target groups (not at the cluster), and application→database reachability
lives in security-group ingress rules. A readable architecture overview needs
the *flow*: ingress LB → compute → datastore. This module derives those edges
deterministically from what was already collected — it never invents a
relationship that has no evidence chain behind it.

Derived edges use dedicated types (``serves``, ``connects_to``) and carry a
``derived`` attribute so the renderer can style them and the audit trail stays
honest.
"""

from __future__ import annotations

from .aws_topology_common import TopologyBuilder, evidence

_COMPUTE_TYPES = {"eks_cluster", "eks_nodegroup", "ecs_cluster", "ecs_service", "autoscaling_group", "ec2_instance", "lambda_function"}
_DATASTORE_TYPES = {"rds_instance", "rds_cluster", "rds_proxy", "dynamodb_table", "elasticache_cluster", "redshift_cluster", "efs_file_system"}


def derive_flow_edges(builder: TopologyBuilder) -> None:
    nodes = builder.nodes
    edges = list(builder.edges)
    types = {nid: str(n.get("type") or "") for nid, n in nodes.items()}

    # nodegroups roll up to their cluster so compute→datastore edges are drawn
    # once per cluster, not once per nodegroup.
    cluster_of: dict[str, str] = {}
    for e in edges:
        if e["type"] == "belongs_to" and types.get(e["source"]) == "eks_nodegroup" and types.get(e["target"]) == "eks_cluster":
            cluster_of[e["source"]] = e["target"]

    _derive_lb_to_compute(builder, nodes, edges, types)
    _derive_compute_to_datastore(builder, nodes, edges, types, cluster_of)
    _derive_proxy_to_instance(builder, nodes, types)


def _derive_lb_to_compute(builder, nodes, edges, types) -> None:
    """A load balancer that routes to (k8s) target groups is really fronting the
    cluster those pods run in. With one compute cluster in the VPC, connect the
    LB straight to it; the target-group detail stays in the data/security views."""
    clusters = [nid for nid, t in types.items() if t == "eks_cluster"]
    if len(clusters) != 1:
        return
    cluster_id = clusters[0]
    lbs_routing = {
        src for src, tgt, etype in ((e["source"], e["target"], e["type"]) for e in edges)
        if etype == "routes_to" and types.get(src) == "load_balancer" and types.get(tgt) == "target_group"
    }
    for lb_id in sorted(lbs_routing):
        builder.add_edge(
            lb_id, cluster_id, "serves", service="elbv2",
            attributes={"derived": True},
            evidence_items=[evidence("elbv2", "describe-target-groups", "routes_to(target_group)->cluster")],
        )


def _derive_compute_to_datastore(builder, nodes, edges, types, cluster_of) -> None:
    """A datastore's security group whose ingress admits a compute security
    group (or that compute's subnet CIDR) means that compute talks to the
    datastore. Resolve the chain: datastore -uses_sg-> SG <-allows_ingress- SG
    <-uses_sg- compute."""
    uses_sg: dict[str, set[str]] = {}
    sg_users: dict[str, set[str]] = {}
    ingress_into: dict[str, set[str]] = {}
    for e in edges:
        if e["type"] == "uses_security_group":
            uses_sg.setdefault(e["source"], set()).add(e["target"])
            sg_users.setdefault(e["target"], set()).add(e["source"])
        elif e["type"] == "allows_ingress_to":
            # source (cidr/sg) is allowed into target sg
            ingress_into.setdefault(e["target"], set()).add(e["source"])

    # compute reachable via a subnet CIDR: subnet cidr -> subnet -> compute
    compute_by_subnet: dict[str, set[str]] = {}
    subnet_cidr: dict[str, str] = {}
    for nid, node in nodes.items():
        if types.get(nid) == "subnet":
            cidr = str((node.get("attributes") or {}).get("cidr_block") or "").strip()
            if cidr:
                subnet_cidr[cidr] = nid
    for e in edges:
        if e["type"] == "uses_subnet" and types.get(e["source"]) in _COMPUTE_TYPES:
            compute_by_subnet.setdefault(e["target"], set()).add(e["source"])
    cidr_label = {nid: str(n.get("label") or "").strip() for nid, n in nodes.items() if types.get(nid) == "cidr"}

    def _emit(edge_source: str, datastore_id: str) -> None:
        source = cluster_of.get(edge_source, edge_source)
        if source == datastore_id or types.get(source) not in _COMPUTE_TYPES:
            return
        builder.add_edge(
            source, datastore_id, "connects_to", service="ec2",
            attributes={"derived": True},
            evidence_items=[evidence("ec2", "describe-security-groups", "ingress-rule")],
        )

    for datastore_id, dtype in list(types.items()):
        if dtype not in _DATASTORE_TYPES:
            continue
        for ds_sg in uses_sg.get(datastore_id, set()):
            for source in ingress_into.get(ds_sg, set()):
                # (a) source is a security group used by compute
                for compute_id in sg_users.get(source, set()):
                    if types.get(compute_id) in _COMPUTE_TYPES:
                        _emit(compute_id, datastore_id)
                # (b) source is a CIDR that maps to a subnet where compute runs
                cidr = cidr_label.get(source)
                subnet_id = subnet_cidr.get(cidr) if cidr else None
                for compute_id in compute_by_subnet.get(subnet_id, set()):
                    _emit(compute_id, datastore_id)


def _derive_proxy_to_instance(builder, nodes, types) -> None:
    """An RDS proxy fronts the DB instances/clusters sharing its name stem
    (``<stem>-proxy`` in front of ``<stem>-one``/``-two``/instances)."""
    proxies = [(nid, str(nodes[nid].get("label") or "")) for nid, t in types.items() if t == "rds_proxy"]
    dbs = [(nid, str(nodes[nid].get("label") or "")) for nid, t in types.items() if t in {"rds_instance", "rds_cluster"}]
    for proxy_id, proxy_label in proxies:
        stem = proxy_label.rsplit("-proxy", 1)[0] if proxy_label.endswith("-proxy") else proxy_label
        for db_id, db_label in dbs:
            if stem and db_label.startswith(stem) and db_id != proxy_id:
                builder.add_edge(
                    proxy_id, db_id, "routes_to", service="rds",
                    attributes={"derived": True},
                    evidence_items=[evidence("rds", "describe-db-proxies", "name-stem")],
                )
