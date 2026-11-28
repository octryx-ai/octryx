"""Role aggregation for the structural AWS overview."""

from __future__ import annotations

from typing import Any

_SUMMARY_NODE_TEMPLATES = {
    "target_group": ("agg_target_groups", "target groups"),
    "route_table": ("agg_route_tables", "route tables"),
}


def curate_overview(
    *,
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    kept_edges: list[tuple[str, str, str]],
    resource_vpc: dict[str, str],
) -> list[str]:
    notes: list[str] = []
    removed: set[str] = set()

    absorbed_tgs = _absorb_routed_target_groups(nodes_by_ref, type_by_ref, kept_edges, removed)
    if absorbed_tgs:
        notes.append(f"{absorbed_tgs} target groups are folded into their load balancers")

    absorbed_asgs = _absorb_backing_asgs(nodes_by_ref, type_by_ref, kept_edges, removed)
    if absorbed_asgs:
        notes.append(f"{absorbed_asgs} auto-scaling groups are folded into their nodegroups")

    folded_ngs = _fold_nodegroups_into_cluster(nodes_by_ref, type_by_ref, kept_edges, removed)
    if folded_ngs:
        notes.append(f"{folded_ngs} EKS nodegroups are folded into their cluster")

    for node_type, (agg_ref, plural) in _SUMMARY_NODE_TEMPLATES.items():
        count = _aggregate_leftovers(
            node_type, agg_ref, nodes_by_ref, type_by_ref, kept_edges, removed, resource_vpc
        )
        if count:
            qualifier = "no load-balancer route" if node_type == "target_group" else "no rendered route"
            notes.append(f"{count} {plural} ({qualifier} in evidence) are summarized into one node")

    for ref in removed:
        nodes_by_ref.pop(ref, None)
        type_by_ref.pop(ref, None)
        resource_vpc.pop(ref, None)
    kept_edges[:] = [
        (source, target, edge_type)
        for source, target, edge_type in kept_edges
        if source not in removed and target not in removed
    ]
    return notes


def _fold_nodegroups_into_cluster(
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    kept_edges: list[tuple[str, str, str]],
    removed: set[str],
) -> int:
    ng_to_cluster: dict[str, str] = {}
    for source, target, edge_type in kept_edges:
        if (
            edge_type == "belongs_to"
            and type_by_ref.get(source) == "eks_nodegroup"
            and type_by_ref.get(target) == "eks_cluster"
        ):
            ng_to_cluster[source] = target
    folded_by_cluster: dict[str, tuple[int, int]] = {}
    for ng_ref, cluster_ref in ng_to_cluster.items():
        node_count = int((nodes_by_ref.get(ng_ref, {}).get("attributes") or {}).get("desired_size") or 0)
        count, nodes = folded_by_cluster.get(cluster_ref, (0, 0))
        folded_by_cluster[cluster_ref] = (count + 1, nodes + node_count)
        removed.add(ng_ref)
    for cluster_ref, (count, node_total) in folded_by_cluster.items():
        node = nodes_by_ref.get(cluster_ref)
        if node is None:
            continue
        attributes = dict(node.get("attributes") or {})
        attributes["folded_nodegroups"] = count
        attributes["folded_node_total"] = node_total
        node["attributes"] = attributes
    # redirect kept edges that pointed at a folded nodegroup onto its cluster
    kept_edges[:] = [
        (ng_to_cluster.get(s, s), ng_to_cluster.get(t, t), et)
        for s, t, et in kept_edges
    ]
    return sum(count for count, _ in folded_by_cluster.values())


def _absorb_routed_target_groups(
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    kept_edges: list[tuple[str, str, str]],
    removed: set[str],
) -> int:
    absorbed_by_lb: dict[str, int] = {}
    for source, target, edge_type in kept_edges:
        if edge_type != "routes_to":
            continue
        if type_by_ref.get(source) == "load_balancer" and type_by_ref.get(target) == "target_group":
            absorbed_by_lb[source] = absorbed_by_lb.get(source, 0) + 1
            removed.add(target)
    for lb_ref, count in absorbed_by_lb.items():
        node = nodes_by_ref[lb_ref]
        attributes = dict(node.get("attributes") or {})
        attributes["absorbed_target_groups"] = count
        node["attributes"] = attributes
    return sum(absorbed_by_lb.values())


def _absorb_backing_asgs(
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    kept_edges: list[tuple[str, str, str]],
    removed: set[str],
) -> int:
    backed_nodegroups: dict[str, list[str]] = {}
    for source, target, edge_type in kept_edges:
        if edge_type != "backs":
            continue
        if type_by_ref.get(source) == "autoscaling_group" and type_by_ref.get(target) == "eks_nodegroup":
            backed_nodegroups.setdefault(source, []).append(target)
    absorbed = 0
    for asg_ref, nodegroups in backed_nodegroups.items():
        if len(nodegroups) != 1:
            continue
        node = nodes_by_ref[nodegroups[0]]
        attributes = dict(node.get("attributes") or {})
        attributes["asg_backed"] = True
        node["attributes"] = attributes
        removed.add(asg_ref)
        absorbed += 1
    return absorbed


def _aggregate_leftovers(
    node_type: str,
    agg_ref: str,
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    kept_edges: list[tuple[str, str, str]],
    removed: set[str],
    resource_vpc: dict[str, str],
) -> int:
    wired = {ref for source, target, _ in kept_edges for ref in (source, target)}
    leftovers = [
        ref
        for ref, ref_type in type_by_ref.items()
        if ref_type == node_type and ref not in wired and ref not in removed
    ]
    if len(leftovers) < 2:
        return 0
    removed.update(leftovers)

    vpc_refs = {resource_vpc[ref] for ref in leftovers if ref in resource_vpc}
    vpc_refs.update(_vpc_by_attribute(nodes_by_ref, leftovers))
    first = nodes_by_ref[leftovers[0]]
    nodes_by_ref[agg_ref] = {
        "ref": agg_ref,
        "type": node_type,
        "label": f"{len(leftovers)} {_SUMMARY_NODE_TEMPLATES[node_type][1]}",
        "service": first.get("service"),
        "region": first.get("region"),
        "attributes": {"summary_count": len(leftovers)},
    }
    type_by_ref[agg_ref] = node_type
    if len(vpc_refs) == 1:
        resource_vpc[agg_ref] = next(iter(vpc_refs))
    return len(leftovers)


def _vpc_by_attribute(
    nodes_by_ref: dict[str, dict[str, Any]],
    refs: list[str],
) -> set[str]:
    vpc_label_to_ref = {
        str(node.get("label") or ""): ref
        for ref, node in nodes_by_ref.items()
        if str(node.get("type") or "") == "vpc"
    }
    found: set[str] = set()
    for ref in refs:
        attrs = nodes_by_ref[ref].get("attributes") or {}
        vpc_ref = vpc_label_to_ref.get(str(attrs.get("vpc_id") or ""))
        if vpc_ref:
            found.add(vpc_ref)
    return found
