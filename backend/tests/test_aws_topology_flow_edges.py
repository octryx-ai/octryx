"""Derived traffic-flow edges (serves / connects_to / proxy routing)."""

from app.tools.connectors.aws_topology_common import TopologyBuilder, node_id
from app.tools.connectors.aws_topology_flow_edges import derive_flow_edges


def _graph():
    b = TopologyBuilder(max_nodes=100)
    for t, i, label, svc in [
        ("load_balancer", "lb1", "ingress-lb", "elbv2"),
        ("target_group", "tg1", "k8s-app-tg", "elbv2"),
        ("eks_cluster", "c1", "prod-eks", "eks"),
        ("eks_nodegroup", "ng1", "ng", "eks"),
        ("rds_proxy", "px1", "app-db-proxy", "rds"),
        ("rds_instance", "db1", "app-db-one", "rds"),
        ("security_group", "ng-sg", "ng-sg", "ec2"),
        ("security_group", "db-sg", "db-sg", "ec2"),
    ]:
        b.add_node(node_id(t, i), node_type=t, label=label, service=svc, region="eu")
    b.add_edge(node_id("load_balancer", "lb1"), node_id("target_group", "tg1"), "routes_to", service="elbv2")
    b.add_edge(node_id("eks_nodegroup", "ng1"), node_id("eks_cluster", "c1"), "belongs_to", service="eks")
    b.add_edge(node_id("eks_nodegroup", "ng1"), node_id("security_group", "ng-sg"), "uses_security_group", service="eks")
    b.add_edge(node_id("rds_instance", "db1"), node_id("security_group", "db-sg"), "uses_security_group", service="rds")
    b.add_edge(node_id("security_group", "ng-sg"), node_id("security_group", "db-sg"), "allows_ingress_to", service="ec2")
    return b


def _derived(builder):
    return {
        (e["source"].split(":", 1)[0], e["type"], e["target"].split(":", 1)[0])
        for e in builder.edges
        if e.get("attributes", {}).get("derived")
    }


def test_full_flow_chain_is_derived():
    b = _graph()
    derive_flow_edges(b)
    flow = _derived(b)
    assert ("load_balancer", "serves", "eks_cluster") in flow
    assert ("eks_cluster", "connects_to", "rds_instance") in flow
    assert ("rds_proxy", "routes_to", "rds_instance") in flow


def test_nodegroup_rolls_up_to_cluster_once():
    b = _graph()
    # a second nodegroup on the same cluster+sg must not create a second edge
    b.add_node(node_id("eks_nodegroup", "ng2"), node_type="eks_nodegroup", label="ng2", service="eks", region="eu")
    b.add_edge(node_id("eks_nodegroup", "ng2"), node_id("eks_cluster", "c1"), "belongs_to", service="eks")
    b.add_edge(node_id("eks_nodegroup", "ng2"), node_id("security_group", "ng-sg"), "uses_security_group", service="eks")
    derive_flow_edges(b)
    connects = [e for e in b.edges if e["type"] == "connects_to" and e.get("attributes", {}).get("derived")]
    assert len(connects) == 1
    assert connects[0]["source"] == node_id("eks_cluster", "c1")


def test_no_lb_serves_edge_with_multiple_clusters():
    b = _graph()
    b.add_node(node_id("eks_cluster", "c2"), node_type="eks_cluster", label="other", service="eks", region="eu")
    derive_flow_edges(b)
    assert not any(e["type"] == "serves" for e in b.edges)


def test_empty_graph_derives_nothing():
    b = TopologyBuilder(max_nodes=100)
    derive_flow_edges(b)
    assert b.edges == []
