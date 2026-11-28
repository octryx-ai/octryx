from app.tools.kubernetes_topology import build_kubernetes_topology_snapshot_from_resources


def _octryx_workload_resources() -> dict:
    return {
        "namespaces": [{"metadata": {"name": "octryx"}, "status": {"phase": "Active"}}],
        "nodes": [{"metadata": {"name": "node-a", "labels": {"node.kubernetes.io/instance-type": "m7i.large"}}}],
        "deployments": [
            {
                "metadata": {"name": "api", "namespace": "octryx", "labels": {"app": "api"}},
                "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "api"}}},
                "status": {"readyReplicas": 1},
            }
        ],
        "pods": [
            {
                "metadata": {"name": "api-1", "namespace": "octryx", "labels": {"app": "api"}},
                "spec": {
                    "nodeName": "node-a",
                    "containers": [{"name": "api"}],
                    "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "api-data"}}],
                },
                "status": {"phase": "Running", "containerStatuses": [{"name": "api", "ready": True}]},
            }
        ],
    }


def _octryx_network_resources() -> dict:
    return {
        "services": [
            {
                "metadata": {"name": "api", "namespace": "octryx"},
                "spec": {"type": "ClusterIP", "selector": {"app": "api"}, "ports": [{"port": 8000}]},
            }
        ],
        "ingresses": [
            {
                "metadata": {"name": "admin", "namespace": "octryx"},
                "spec": {
                    "ingressClassName": "alb",
                    "rules": [
                        {
                            "host": "octryx.example.test",
                            "http": {
                                "paths": [
                                    {"path": "/", "backend": {"service": {"name": "api", "port": {"number": 8000}}}}
                                ]
                            },
                        }
                    ],
                },
            }
        ],
        "pvcs": [
            {
                "metadata": {"name": "api-data", "namespace": "octryx"},
                "spec": {"storageClassName": "gp3", "resources": {"requests": {"storage": "20Gi"}}},
                "status": {"phase": "Bound"},
            }
        ],
        "endpoints": [
            {
                "metadata": {"name": "api", "namespace": "octryx"},
                "subsets": [{"addresses": [{"ip": "10.0.0.10", "targetRef": {"kind": "Pod", "name": "api-1"}}]}],
            }
        ],
        "networkpolicies": [
            {
                "metadata": {"name": "default-deny", "namespace": "octryx"},
                "spec": {"podSelector": {}, "policyTypes": ["Ingress"]},
            }
        ],
    }


def _octryx_api_resources() -> dict:
    return {**_octryx_workload_resources(), **_octryx_network_resources()}


def test_kubernetes_topology_snapshot_builds_relationship_graph_from_resources():
    resources = _octryx_api_resources()

    snapshot = build_kubernetes_topology_snapshot_from_resources(
        resources,
        source="test",
        scope={"namespace": "octryx", "all_namespaces": False},
        diagram_detail="full",
        max_nodes=100,
    )

    refs = {node["ref"] for node in snapshot["diagram_brief"]["selected_nodes"]}
    edges = {
        (edge["source_ref"], edge["target_ref"], edge["type"])
        for edge in snapshot["diagram_brief"]["selected_edges"]
    }

    assert "k8s:deployment:octryx:api" in refs
    assert "k8s:service:octryx:api" in refs
    assert "k8s:ingress:octryx:admin" in refs
    assert (
        "k8s:ingress:octryx:admin",
        "k8s:service:octryx:api",
        "routes_to",
    ) in edges
    assert (
        "k8s:service:octryx:api",
        "k8s:pod:octryx:api-1",
        "selects_pod",
    ) in edges
    assert (
        "k8s:deployment:octryx:api",
        "k8s:pod:octryx:api-1",
        "owns_pod",
    ) in edges
    assert (
        "k8s:pod:octryx:api-1",
        "k8s:persistent_volume_claim:octryx:api-data",
        "mounts",
    ) in edges
    assert (
        "k8s:network_policy:octryx:default-deny",
        "k8s:pod:octryx:api-1",
        "selects_pod",
    ) in edges
