"""Per-application detail candidates and listener-port rendering."""

import json

from app.services.diagrams.aws_topology_detail_candidates import build_aws_topology_detail_candidates
from app.services.diagrams.aws_topology_diagram import build_aws_topology_detail_diagram_tool_calls


def _contract():
    return {"workflow_id": "generic_diagram", "diagram_source": "aws_topology_snapshot", "topic": ""}


def _shape_library():
    return {
        "library": "aws4",
        "prefix": "mxgraph.aws4",
        "matched_shapes": [
            {"requested": name, "shape": name, "match_type": "exact"}
            for name in ["application_load_balancer", "elastic_load_balancing", "security_group", "waf"]
        ],
    }


def _topology_with_apps():
    return {
        "account_id": "111122223333",
        "region": "eu-central-1",
        "service_summary": {"resource_node_count": 8, "edge_count": 6},
        "diagram_brief": {
            "mode": "full",
            "selected_nodes": [
                {"ref": "lb_a", "type": "load_balancer", "label": "k8s-traefik-traefik-0abc123def", "service": "elbv2",
                 "attributes": {"scheme": "internet-facing", "listeners": ["HTTPS:443", "HTTP:80"]}},
                {"ref": "tg_a1", "type": "target_group", "label": "k8s-traefik-a-11aa22bb33", "service": "elbv2"},
                {"ref": "tg_a2", "type": "target_group", "label": "k8s-traefik-b-44cc55dd66", "service": "elbv2"},
                {"ref": "sg_a", "type": "security_group", "label": "traefik-sg", "service": "ec2"},
                {"ref": "waf1", "type": "waf_web_acl", "label": "edge-waf", "service": "wafv2"},
                {"ref": "lb_b", "type": "load_balancer", "label": "k8s-argocd-argocd-99ff88ee77", "service": "elbv2",
                 "attributes": {"scheme": "internal", "listeners": ["HTTPS:443"]}},
                {"ref": "tg_b1", "type": "target_group", "label": "k8s-argocd-x-77aa88bb99", "service": "elbv2"},
                {"ref": "sg_b", "type": "security_group", "label": "argocd-sg", "service": "ec2"},
            ],
            "selected_edges": [
                {"source_ref": "lb_a", "target_ref": "tg_a1", "type": "routes_to", "service": "elbv2",
                 "attributes": {"listeners": ["HTTPS:443"]}},
                {"source_ref": "lb_a", "target_ref": "tg_a2", "type": "routes_to", "service": "elbv2",
                 "attributes": {"listeners": ["HTTP:80"]}},
                {"source_ref": "lb_a", "target_ref": "sg_a", "type": "uses_security_group", "service": "elbv2"},
                {"source_ref": "waf1", "target_ref": "lb_a", "type": "protects", "service": "wafv2"},
                {"source_ref": "lb_b", "target_ref": "tg_b1", "type": "routes_to", "service": "elbv2"},
                {"source_ref": "lb_b", "target_ref": "sg_b", "type": "uses_security_group", "service": "elbv2"},
            ],
        },
    }


def test_application_candidates_are_per_load_balancer():
    candidates = build_aws_topology_detail_candidates(_topology_with_apps())
    app_candidates = [c for c in candidates if c["id"].startswith("app_")]
    titles = {c["title"] for c in app_candidates}
    # duplicate-token k8s names collapse: k8s-traefik-traefik-<hash> -> "traefik"
    assert "Application detail - traefik" in titles
    assert "Application detail - argocd" in titles
    # the busier app (more edges) ranks first among app candidates
    traefik = next(c for c in app_candidates if "traefik" in c["title"])
    assert traefik["estimated_edges"] >= 3
    assert set(traefik["node_refs"]) >= {"lb_a", "tg_a1", "tg_a2", "sg_a", "waf1"}
    # argocd app must NOT bleed into traefik's node set
    assert "lb_b" not in traefik["node_refs"]


def test_application_detail_diagram_pins_exact_nodes():
    topology = _topology_with_apps()
    candidates = build_aws_topology_detail_candidates(topology)
    traefik = next(c for c in candidates if c["id"].startswith("app_") and "traefik" in c["title"])

    calls = build_aws_topology_detail_diagram_tool_calls(
        {"topic": "aws"}, topology, _shape_library(), {"create_diagram"}, max_diagrams=5
    )
    xmls = [json.loads(call["function"]["arguments"])["xml"] for call in calls]
    app_xml = next((xml for xml in xmls if "traefik" in xml and "argocd" not in xml), None)
    assert app_xml is not None, "expected a traefik-only application diagram"
    # exact-node pinning: argocd resources are absent from the traefik diagram
    assert "argocd" not in app_xml
    assert 'id="lb_a"' in app_xml or "traefik" in app_xml
    assert traefik["estimated_edges"] >= 3
