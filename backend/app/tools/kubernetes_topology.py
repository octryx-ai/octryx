"""The Kubernetes topology snapshot built from listed resources: nodes, edges and the diagram brief."""

from collections import Counter
from datetime import UTC, datetime
from typing import Any

_TOPOLOGY_NODE_PRIORITY = {
    "namespace": 10,
    "ingress": 20,
    "service": 30,
    "deployment": 40,
    "statefulset": 41,
    "daemonset": 42,
    "job": 50,
    "cronjob": 51,
    "network_policy": 60,
    "persistent_volume_claim": 70,
    "pod": 80,
    "node": 90,
}


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("metadata") if isinstance(item.get("metadata"), dict) else {}


def _spec(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("spec") if isinstance(item.get("spec"), dict) else {}


def _status(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("status") if isinstance(item.get("status"), dict) else {}


def _labels(item: dict[str, Any]) -> dict[str, str]:
    raw = _metadata(item).get("labels")
    return {str(key): str(value) for key, value in raw.items()} if isinstance(raw, dict) else {}


def _selector_matches(
    selector: dict[str, Any] | None,
    labels: dict[str, str],
    *,
    empty_matches_all: bool = False,
) -> bool:
    if not selector:
        return empty_matches_all
    match_labels = selector.get("matchLabels") if isinstance(selector.get("matchLabels"), dict) else selector
    if not isinstance(match_labels, dict):
        return False
    if not match_labels:
        return empty_matches_all
    return all(labels.get(str(key)) == str(value) for key, value in match_labels.items())


def _resource_ref(node_type: str, namespace: str | None, name: str) -> str:
    if namespace:
        return f"k8s:{node_type}:{namespace}:{name}"
    return f"k8s:{node_type}:{name}"


class _Topology:
    # The snapshot's nodes (the first one per ref stays) and its edges (each source, target, type and label once).
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._edge_keys: set[tuple[str, str, str, str]] = set()

    def node(self, node: dict[str, Any]) -> None:
        ref = str(node.get("ref") or "").strip()
        if ref and ref not in self.nodes:
            self.nodes[ref] = node

    def edge(self, source_ref: str, target_ref: str, edge_type: str, *, label: str | None = None) -> None:
        if not source_ref or not target_ref or source_ref == target_ref:
            return
        key = (source_ref, target_ref, edge_type, label or "")
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        edge = {"source_ref": source_ref, "target_ref": target_ref, "type": edge_type}
        if label:
            edge["label"] = label
        self.edges.append(edge)

    def in_namespace(self, ref: str, namespace: str) -> None:
        self.edge(ref, _resource_ref("namespace", None, namespace), "in_namespace")


def _named(item: dict[str, Any]) -> tuple[str, str]:
    meta = _metadata(item)
    return str(meta.get("namespace") or "default"), str(meta.get("name") or "").strip()


def build_kubernetes_topology_snapshot_from_resources(
    resources: dict[str, list[dict[str, Any]]],
    *,
    source: str,
    scope: dict[str, Any],
    diagram_detail: str = "full",
    max_nodes: int = 1000,
) -> dict[str, Any]:
    topology = _Topology()
    _add_namespaces(topology, resources)
    pods_by_namespace = _add_pods(topology, resources.get("pods", []))
    _add_cluster_nodes(topology, resources.get("nodes", []))
    _add_workloads(topology, resources, pods_by_namespace)
    _add_services(topology, resources, pods_by_namespace)
    _add_ingresses(topology, resources.get("ingresses", []))
    _add_pvcs(topology, resources.get("pvcs", []))
    _add_network_policies(topology, resources.get("networkpolicies", []), pods_by_namespace)
    return _snapshot(topology, source=source, scope=scope, diagram_detail=diagram_detail, max_nodes=max_nodes)


def _add_namespaces(topology: _Topology, resources: dict[str, list[dict[str, Any]]]) -> None:
    for ns in resources.get("namespaces", []):
        name = str(_metadata(ns).get("name") or "").strip()
        if name:
            topology.node({"ref": _resource_ref("namespace", None, name), "type": "namespace", "label": name,
                           "namespace": name, "attributes": {"phase": _status(ns).get("phase")}})
    # A namespace a pod names is a node even when the namespaces were not listed.
    for namespace in sorted({str(_metadata(pod).get("namespace") or "default") for pod in resources.get("pods", [])}):
        topology.node({"ref": _resource_ref("namespace", None, namespace), "type": "namespace", "label": namespace,
                       "namespace": namespace, "attributes": {}})


def _add_pods(topology: _Topology, pods: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    pods_by_namespace: dict[str, list[dict[str, Any]]] = {}
    for pod in pods:
        namespace, name = _named(pod)
        if not name:
            continue
        ref = _resource_ref("pod", namespace, name)
        ready = sum(1 for item in _status(pod).get("containerStatuses", []) if item.get("ready"))
        containers = len(_spec(pod).get("containers", []))
        topology.node({"ref": ref, "type": "pod", "label": name, "namespace": namespace, "attributes": {
            "phase": _status(pod).get("phase"), "ready": f"{ready}/{containers}" if containers else "",
            "node": _spec(pod).get("nodeName")}, "labels": _labels(pod)})
        pods_by_namespace.setdefault(namespace, []).append(pod)
        topology.in_namespace(ref, namespace)
        node_name = str(_spec(pod).get("nodeName") or "").strip()
        if node_name:
            topology.edge(ref, _resource_ref("node", None, node_name), "scheduled_on")
        for volume in _spec(pod).get("volumes", []) or []:
            claim = (volume.get("persistentVolumeClaim") or {}).get("claimName") if isinstance(volume, dict) else None
            if claim:
                topology.edge(ref, _resource_ref("persistent_volume_claim", namespace, str(claim)), "mounts")
    return pods_by_namespace


def _add_cluster_nodes(topology: _Topology, nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        name = str(_metadata(node).get("name") or "").strip()
        if not name:
            continue
        ready = next((condition.get("status") == "True" for condition in _status(node).get("conditions", [])
                      if condition.get("type") == "Ready"), None)
        topology.node({"ref": _resource_ref("node", None, name), "type": "node", "label": name, "attributes": {
            "ready": ready, "type": _labels(node).get("node.kubernetes.io/instance-type", "")}})


def _select_pods(topology: _Topology, ref: str, namespace: str, pods_by_namespace: dict[str, list[dict[str, Any]]],
                 selector: dict[str, Any] | None, edge_type: str, *, empty_matches_all: bool = False) -> None:
    for pod in pods_by_namespace.get(namespace, []):
        if _selector_matches(selector, _labels(pod), empty_matches_all=empty_matches_all):
            topology.edge(ref, _resource_ref("pod", namespace, str(_metadata(pod).get("name") or "")), edge_type)


def _add_workloads(topology: _Topology, resources: dict[str, list[dict[str, Any]]],
                   pods_by_namespace: dict[str, list[dict[str, Any]]]) -> None:
    for resource_key, node_type in (("deployments", "deployment"), ("statefulsets", "statefulset"),
                                    ("daemonsets", "daemonset"), ("jobs", "job"), ("cronjobs", "cronjob")):
        for item in resources.get(resource_key, []):
            namespace, name = _named(item)
            if not name:
                continue
            spec, status = _spec(item), _status(item)
            ref = _resource_ref(node_type, namespace, name)
            topology.node({"ref": ref, "type": node_type, "label": name, "namespace": namespace, "attributes": {
                "replicas": spec.get("replicas"),
                "ready": status.get("readyReplicas") or status.get("numberReady") or status.get("succeeded"),
            }, "labels": _labels(item)})
            topology.in_namespace(ref, namespace)
            if node_type != "cronjob":
                selector = spec.get("selector") if isinstance(spec.get("selector"), dict) else {}
                _select_pods(topology, ref, namespace, pods_by_namespace, selector, "owns_pod")


def _add_services(topology: _Topology, resources: dict[str, list[dict[str, Any]]],
                  pods_by_namespace: dict[str, list[dict[str, Any]]]) -> None:
    for service in resources.get("services", []):
        namespace, name = _named(service)
        if not name:
            continue
        spec = _spec(service)
        ref = _resource_ref("service", namespace, name)
        ports = [str(port.get("port")) for port in spec.get("ports", []) or []
                 if isinstance(port, dict) and port.get("port") is not None]
        topology.node({"ref": ref, "type": "service", "label": name, "namespace": namespace, "attributes": {
            "type": spec.get("type"), "ports": ports, "selector": spec.get("selector")}})
        topology.in_namespace(ref, namespace)
        _select_pods(topology, ref, namespace, pods_by_namespace, spec.get("selector"), "selects_pod")
    for endpoint in resources.get("endpoints", []):
        namespace, service_name = _named(endpoint)
        service_ref = _resource_ref("service", namespace, service_name)
        for subset in endpoint.get("subsets", []) or []:
            for address in [*(subset.get("addresses") or []), *(subset.get("notReadyAddresses") or [])]:
                target = address.get("targetRef") if isinstance(address, dict) else {}
                if isinstance(target, dict) and target.get("kind") == "Pod" and target.get("name"):
                    topology.edge(service_ref, _resource_ref("pod", namespace, str(target["name"])), "backs_service")


def _add_ingresses(topology: _Topology, ingresses: list[dict[str, Any]]) -> None:
    for ingress in ingresses:
        namespace, name = _named(ingress)
        if not name:
            continue
        ref = _resource_ref("ingress", namespace, name)
        topology.node({"ref": ref, "type": "ingress", "label": name, "namespace": namespace,
                       "attributes": {"type": _spec(ingress).get("ingressClassName")}})
        topology.in_namespace(ref, namespace)
        for rule in _spec(ingress).get("rules", []) or []:
            host = str(rule.get("host") or "").strip()
            for path in ((rule.get("http") or {}).get("paths") or []):
                service = ((path.get("backend") or {}).get("service") or {}).get("name")
                if service:
                    topology.edge(ref, _resource_ref("service", namespace, str(service)), "routes_to",
                                  label=host or str(path.get("path") or "routes"))


def _add_pvcs(topology: _Topology, pvcs: list[dict[str, Any]]) -> None:
    for pvc in pvcs:
        namespace, name = _named(pvc)
        if name:
            topology.node({"ref": _resource_ref("persistent_volume_claim", namespace, name),
                           "type": "persistent_volume_claim", "label": name, "namespace": namespace, "attributes": {
                               "phase": _status(pvc).get("phase"),
                               "storage_class": _spec(pvc).get("storageClassName"),
                               "requested": ((_spec(pvc).get("resources") or {}).get("requests") or {}).get("storage"),
                           }})


def _add_network_policies(topology: _Topology, policies: list[dict[str, Any]],
                          pods_by_namespace: dict[str, list[dict[str, Any]]]) -> None:
    for policy in policies:
        namespace, name = _named(policy)
        if not name:
            continue
        spec = _spec(policy)
        ref = _resource_ref("network_policy", namespace, name)
        topology.node({"ref": ref, "type": "network_policy", "label": name, "namespace": namespace, "attributes": {
            "policy_types": spec.get("policyTypes", []), "ingress_rules": len(spec.get("ingress", []) or []),
            "egress_rules": len(spec.get("egress", []) or [])}})
        topology.in_namespace(ref, namespace)
        _select_pods(topology, ref, namespace, pods_by_namespace, spec.get("podSelector"), "selects_pod",
                     empty_matches_all=True)


def _snapshot(topology: _Topology, *, source: str, scope: dict[str, Any], diagram_detail: str,
              max_nodes: int) -> dict[str, Any]:
    edges = topology.edges
    ordered_nodes = sorted(topology.nodes.values(), key=lambda node: (
        _TOPOLOGY_NODE_PRIORITY.get(str(node.get("type") or ""), 100), str(node.get("namespace") or ""),
        str(node.get("label") or "")))
    selected_nodes = ordered_nodes[: max(1, max_nodes)]
    selected_refs = {str(node.get("ref") or "") for node in selected_nodes}
    selected_edges = [edge for edge in edges if str(edge.get("source_ref") or "") in selected_refs
                      and str(edge.get("target_ref") or "") in selected_refs]
    node_counts = Counter(str(node.get("type") or "unknown") for node in ordered_nodes)
    return {
        "source": source,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": scope,
        "topology_summary": {
            "resource_node_count": len(ordered_nodes),
            "edge_count": len(edges),
            "selected_resource_node_count": len(selected_nodes),
            "selected_edge_count": len(selected_edges),
            "node_counts_by_type": dict(sorted(node_counts.items())),
        },
        "nodes": ordered_nodes,
        "edges": edges,
        "diagram_brief": {
            "mode": diagram_detail,
            "selected_nodes": selected_nodes,
            "selected_edges": selected_edges,
            "omitted_node_count": max(0, len(ordered_nodes) - len(selected_nodes)),
            "omitted_edge_count": max(0, len(edges) - len(selected_edges)),
        },
    }
