"""Kubernetes tool implementations.

Under an alert scope (``alert_scope``) the namespaced tools read only the mapped target's namespace (the default
when the model names none) and connection; another namespace is refused (``namespace_out_of_scope``) and so is any
kubectl argument that leaves it (``kubectl_scope_refusal``). The cluster evidence tools (``get_pod_logs``,
``list_failed_pods``, ``get_k8s_events``) put an ``evidence`` envelope on every result.
"""

import functools
import json
import logging
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_KUBERNETES, egress_transport

from ..services.execution_runtime import (
    execute_with_runtime,
    resolve_execution_runtime_config,
    workspace_mount_for_path,
)
from ..services.process_output_redaction import redact_process_output
from ..services.workflow_checks.evidence_families import (
    EMPTY,
    OK,
    REFUSED,
    TOOL_FAMILY,
    UNAVAILABLE,
    evidence_envelope,
    with_envelope,
)
from .alert_scope import AlertScope, run_alert_scope
from .context import ToolContext
from .kubernetes_kubectl_argv import (
    NAMESPACE_OUT_OF_SCOPE,
    kubectl_command,
    kubectl_scope_refusal,
    kubectl_subcommand_refusal,
)
from .kubernetes_transport import kubernetes_tls_verify

logger = logging.getLogger(__name__)


def _k8s_transport(verify):
    """The pinned private-network egress transport for the Kubernetes API (keeps its CA/verify setting)."""
    return egress_transport(CONNECTION_KUBERNETES, verify=verify)


def _warn_if_tls_disabled(context: ToolContext, source: str) -> None:
    """Log a warning when k8s_verify_tls is explicitly disabled."""
    if context.project_config.get("k8s_verify_tls") is False:
        logger.warning(
            "k8s_verify_tls is False for project %s — TLS verification "
            "is disabled for %s. This is insecure; only set to False in controlled "
            "test environments.",
            context.project_config.get("project_id", "?"),
            source,
        )


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_SA_TOKEN_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
_SA_CA_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")


def _resolve_k8s_api_config(context: ToolContext) -> tuple[str | None, dict[str, str], Any]:
    """Return (api_url, headers, verify) with in-cluster auto-detection."""
    k8s_api = context.project_config.get("k8s_api_url")
    k8s_token = context.project_config.get("k8s_token")
    ca_path = None

    if not k8s_api and _SA_TOKEN_PATH.exists():
        k8s_api = "https://kubernetes.default.svc"

    if not k8s_token and _SA_TOKEN_PATH.exists():
        k8s_token = _SA_TOKEN_PATH.read_text().strip()
        if _SA_CA_PATH.exists():
            ca_path = str(_SA_CA_PATH)

    headers = {"Authorization": f"Bearer {k8s_token}"} if k8s_token else {}
    return k8s_api, headers, kubernetes_tls_verify(context.project_config, in_cluster_ca=ca_path)


def _workspace_root(context: ToolContext) -> Path:
    return Path(context.workspace_root or Path.cwd()).resolve()


def _resolve_path(context: ToolContext, raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    expanded = Path(os.path.expanduser(raw_path))
    if expanded.is_absolute():
        return str(expanded)
    return str((_workspace_root(context) / expanded).resolve())


def _kubectl_binary(context: ToolContext) -> str:
    return _resolve_path(context, context.project_config.get("kubectl_path")) or "kubectl"


async def _run_kubectl(
    context: ToolContext,
    args: list[str],
    timeout_sec: int = 20,
    *,
    namespace: str | None = None,
) -> tuple[int, str, str]:
    """Run ``kubectl <args>``; ``args[0]`` is the subcommand, ``namespace`` overrides the project default."""
    # Reject a missing or unknown subcommand before any side-effects
    refusal = kubectl_subcommand_refusal(args)
    if refusal:
        return 1, "", refusal
    # Under an alert scope only the target's namespace, whoever called (defence in depth for every tool).
    scope = await run_alert_scope(context)
    if scope is not None and scope.namespace:
        refusal = kubectl_scope_refusal(args, namespace=scope.namespace) or (
            NAMESPACE_OUT_OF_SCOPE if namespace and namespace != scope.namespace else None)
        if refusal:
            return 1, "", refusal
        namespace = scope.namespace  # never the Workspace default namespace

    workspace_root = _workspace_root(context)
    runtime_config = await resolve_execution_runtime_config(context.db, project_config=context.project_config)
    kubeconfig_host = _resolve_path(context, context.project_config.get("kubeconfig_path"))
    kubeconfig_runtime = kubeconfig_host
    mounts = []
    if runtime_config.provider == "docker":
        if kubeconfig_host:
            kubeconfig_path = Path(kubeconfig_host).resolve()
            if workspace_root not in kubeconfig_path.parents and kubeconfig_path != workspace_root:
                mounts.append(
                    workspace_mount_for_path(
                        host_path=kubeconfig_path,
                        container_path="/runtime-mounts/kubeconfig",
                        read_only=True,
                    )
                )
                kubeconfig_runtime = "/runtime-mounts/kubeconfig"
        kubectl_binary = str(context.project_config.get("kubectl_container_path") or "kubectl").strip() or "kubectl"
    else:
        kubectl_binary = _kubectl_binary(context)

    command = kubectl_command(
        kubectl_binary,
        args,
        kubeconfig=kubeconfig_runtime,
        kube_context=context.project_config.get("k8s_context"),
        namespace=namespace or context.project_config.get("k8s_namespace"),
    )
    runtime_result = await execute_with_runtime(
        db=context.db,
        project_config=context.project_config,
        command=command,
        cwd=workspace_root,
        workspace_root=workspace_root,
        timeout_sec=timeout_sec,
        mounts=mounts,
        guard_foreign_build=False,  # the configured kubectl binary, not repository content
    )
    if runtime_result.timed_out:
        return 124, "", runtime_result.stderr or f"kubectl timed out after {timeout_sec}s"
    if runtime_result.exit_code is None:
        return 125, "", runtime_result.stderr or "kubectl could not be executed"
    return (runtime_result.exit_code, runtime_result.stdout, runtime_result.stderr)


def _kubectl_failure(returncode: int) -> dict[str, Any]:
    """A failed kubectl call as fixed facts; its stderr/stdout can carry server URLs and tokens."""
    return {
        "error": f"kubectl_command_failed exit_code={returncode}",
        "error_code": "kubectl_command_failed",
        "exit_code": returncode,
    }


def _should_use_kubectl(context: ToolContext) -> bool:
    if _as_bool(context.project_config.get("k8s_use_kubectl"), False):
        return True
    return bool(context.project_config.get("kubeconfig_path") or context.project_config.get("k8s_context"))


CONNECTION_OUT_OF_SCOPE = "connection_out_of_scope"
_TOPOLOGY_TOOL = "kubernetes_topology_snapshot"


def _scope_refusal(params: dict, context: ToolContext, scope: AlertScope) -> str | None:
    if scope.connection_id and context.connection_id and context.connection_id != scope.connection_id:
        return CONNECTION_OUT_OF_SCOPE
    requested = str(params.get("namespace") or "").strip()
    if scope.namespace and requested and requested != scope.namespace:
        return NAMESPACE_OUT_OF_SCOPE
    return None


def _evidence_count(name: str, result: dict[str, Any]) -> int:
    if name == "get_pod_logs":
        return 1 if str(result.get("logs") or "").strip() else 0
    value = result.get("failed_count" if name == "list_failed_pods" else "total_events")
    return value if type(value) is int and value > 0 else 0


def _k8s_envelope(status: str, scope: AlertScope | None, namespace: Any, count: int, reason: str = "") -> dict:
    return evidence_envelope("kubernetes", status, target_id=scope.target_id if scope else None,
                             namespace=str(namespace or "") or None, window=None, count=count, reason=reason)


def _alert_scoped(execute):
    """A namespaced tool under the run's alert scope: the target's namespace, refusals, the evidence envelope."""

    @functools.wraps(execute)
    async def scoped(self, params: dict, context: ToolContext) -> dict[str, Any]:
        family = TOOL_FAMILY.get(self.name) == "kubernetes"
        scope = await run_alert_scope(context)
        if scope is not None:
            refusal = _scope_refusal(params, context, scope)
            if refusal:
                refused = {"error": refusal, "code": refusal, "namespace": params.get("namespace"),
                           "scope_namespace": scope.namespace}
                return with_envelope(refused, _k8s_envelope(REFUSED, scope, scope.namespace, 0, refusal)) \
                    if family else refused
            if scope.namespace:
                params = {**params, "namespace": scope.namespace}
                if self.name == _TOPOLOGY_TOOL:
                    params["all_namespaces"] = False
        if not family:
            return await execute(self, params, context)
        namespace = params.get("namespace")
        try:
            result = await execute(self, params, context)
        except httpx.HTTPStatusError as error:
            code = f"kubernetes_http_{error.response.status_code}"
            return with_envelope({"error": code, "code": code}, _k8s_envelope(UNAVAILABLE, scope, namespace, 0, code))
        except (httpx.HTTPError, ValueError) as error:
            code = f"kubernetes_unavailable: {type(error).__name__}"
            return with_envelope({"error": code, "code": "kubernetes_unavailable"},
                                 _k8s_envelope(UNAVAILABLE, scope, namespace, 0, code))
        if not isinstance(result, dict):
            return result
        if result.get("error"):
            code = str(result.get("error_code") or result.get("code") or result.get("error"))[:120]
            return with_envelope(result, _k8s_envelope(UNAVAILABLE, scope, namespace, 0, code))
        count = _evidence_count(self.name, result)
        return with_envelope(result, _k8s_envelope(OK if count else EMPTY, scope, namespace, count))

    return scoped


_TOPOLOGY_NAMESPACED_KINDS = {
    "deployments": ("apps", "v1", "deployments"),
    "statefulsets": ("apps", "v1", "statefulsets"),
    "daemonsets": ("apps", "v1", "daemonsets"),
    "jobs": ("batch", "v1", "jobs"),
    "cronjobs": ("batch", "v1", "cronjobs"),
    "pods": ("", "v1", "pods"),
    "services": ("", "v1", "services"),
    "ingresses": ("networking.k8s.io", "v1", "ingresses"),
    "pvcs": ("", "v1", "persistentvolumeclaims"),
    "endpoints": ("", "v1", "endpoints"),
    "networkpolicies": ("networking.k8s.io", "v1", "networkpolicies"),
}
_WORKLOAD_KIND_TO_TYPE = {
    "Deployment": "deployment",
    "StatefulSet": "statefulset",
    "DaemonSet": "daemonset",
    "Job": "job",
    "CronJob": "cronjob",
}
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


def _add_topology_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    ref = str(node.get("ref") or "").strip()
    if ref and ref not in nodes:
        nodes[ref] = node


def _add_topology_edge(
    edges: list[dict[str, Any]],
    edge_keys: set[tuple[str, str, str, str]],
    source_ref: str,
    target_ref: str,
    edge_type: str,
    *,
    label: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> None:
    if not source_ref or not target_ref or source_ref == target_ref:
        return
    key = (source_ref, target_ref, edge_type, label or "")
    if key in edge_keys:
        return
    edge_keys.add(key)
    edge = {"source_ref": source_ref, "target_ref": target_ref, "type": edge_type}
    if label:
        edge["label"] = label
    if attributes:
        edge["attributes"] = attributes
    edges.append(edge)


def build_kubernetes_topology_snapshot_from_resources(
    resources: dict[str, list[dict[str, Any]]],
    *,
    source: str,
    scope: dict[str, Any],
    diagram_detail: str = "full",
    max_nodes: int = 1000,
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str, str]] = set()

    for ns in resources.get("namespaces", []):
        name = str(_metadata(ns).get("name") or "").strip()
        if not name:
            continue
        _add_topology_node(
            nodes,
            {
                "ref": _resource_ref("namespace", None, name),
                "type": "namespace",
                "label": name,
                "namespace": name,
                "attributes": {"phase": _status(ns).get("phase")},
            },
        )

    pod_items = resources.get("pods", [])
    pod_by_namespace = {str(_metadata(pod).get("namespace") or "default") for pod in pod_items}
    for namespace in sorted(pod_by_namespace):
        ns_ref = _resource_ref("namespace", None, namespace)
        _add_topology_node(
            nodes,
            {"ref": ns_ref, "type": "namespace", "label": namespace, "namespace": namespace, "attributes": {}},
        )

    pods_by_namespace: dict[str, list[dict[str, Any]]] = {}
    for pod in pod_items:
        meta = _metadata(pod)
        namespace = str(meta.get("namespace") or "default")
        name = str(meta.get("name") or "").strip()
        if not name:
            continue
        ref = _resource_ref("pod", namespace, name)
        ready = sum(1 for item in _status(pod).get("containerStatuses", []) if item.get("ready"))
        containers = len(_spec(pod).get("containers", []))
        _add_topology_node(
            nodes,
            {
                "ref": ref,
                "type": "pod",
                "label": name,
                "namespace": namespace,
                "attributes": {
                    "phase": _status(pod).get("phase"),
                    "ready": f"{ready}/{containers}" if containers else "",
                    "node": _spec(pod).get("nodeName"),
                },
                "labels": _labels(pod),
            },
        )
        pods_by_namespace.setdefault(namespace, []).append(pod)
        _add_topology_edge(edges, edge_keys, ref, _resource_ref("namespace", None, namespace), "in_namespace")

        node_name = str(_spec(pod).get("nodeName") or "").strip()
        if node_name:
            _add_topology_edge(edges, edge_keys, ref, _resource_ref("node", None, node_name), "scheduled_on")
        for volume in _spec(pod).get("volumes", []) or []:
            claim = (volume.get("persistentVolumeClaim") or {}).get("claimName") if isinstance(volume, dict) else None
            if claim:
                _add_topology_edge(
                    edges,
                    edge_keys,
                    ref,
                    _resource_ref("persistent_volume_claim", namespace, str(claim)),
                    "mounts",
                )

    for node in resources.get("nodes", []):
        name = str(_metadata(node).get("name") or "").strip()
        if not name:
            continue
        ready = next(
            (
                condition.get("status") == "True"
                for condition in _status(node).get("conditions", [])
                if condition.get("type") == "Ready"
            ),
            None,
        )
        _add_topology_node(
            nodes,
            {
                "ref": _resource_ref("node", None, name),
                "type": "node",
                "label": name,
                "attributes": {
                    "ready": ready,
                    "type": _labels(node).get("node.kubernetes.io/instance-type", ""),
                },
            },
        )

    for resource_key, node_type in (
        ("deployments", "deployment"),
        ("statefulsets", "statefulset"),
        ("daemonsets", "daemonset"),
        ("jobs", "job"),
        ("cronjobs", "cronjob"),
    ):
        for item in resources.get(resource_key, []):
            meta = _metadata(item)
            spec = _spec(item)
            status = _status(item)
            namespace = str(meta.get("namespace") or "default")
            name = str(meta.get("name") or "").strip()
            if not name:
                continue
            ref = _resource_ref(node_type, namespace, name)
            _add_topology_node(
                nodes,
                {
                    "ref": ref,
                    "type": node_type,
                    "label": name,
                    "namespace": namespace,
                    "attributes": {
                        "replicas": spec.get("replicas"),
                        "ready": status.get("readyReplicas") or status.get("numberReady") or status.get("succeeded"),
                    },
                    "labels": _labels(item),
                },
            )
            _add_topology_edge(edges, edge_keys, ref, _resource_ref("namespace", None, namespace), "in_namespace")
            selector = spec.get("selector") if isinstance(spec.get("selector"), dict) else {}
            if node_type == "cronjob":
                continue
            for pod in pods_by_namespace.get(namespace, []):
                pod_ref = _resource_ref("pod", namespace, str(_metadata(pod).get("name") or ""))
                if _selector_matches(selector, _labels(pod)):
                    _add_topology_edge(edges, edge_keys, ref, pod_ref, "owns_pod")

    for service in resources.get("services", []):
        meta = _metadata(service)
        spec = _spec(service)
        namespace = str(meta.get("namespace") or "default")
        name = str(meta.get("name") or "").strip()
        if not name:
            continue
        ref = _resource_ref("service", namespace, name)
        ports = [
            str(port.get("port"))
            for port in spec.get("ports", []) or []
            if isinstance(port, dict) and port.get("port") is not None
        ]
        _add_topology_node(
            nodes,
            {
                "ref": ref,
                "type": "service",
                "label": name,
                "namespace": namespace,
                "attributes": {"type": spec.get("type"), "ports": ports, "selector": spec.get("selector")},
            },
        )
        _add_topology_edge(edges, edge_keys, ref, _resource_ref("namespace", None, namespace), "in_namespace")
        for pod in pods_by_namespace.get(namespace, []):
            pod_ref = _resource_ref("pod", namespace, str(_metadata(pod).get("name") or ""))
            if _selector_matches(spec.get("selector"), _labels(pod)):
                _add_topology_edge(edges, edge_keys, ref, pod_ref, "selects_pod")

    for endpoint in resources.get("endpoints", []):
        namespace = str(_metadata(endpoint).get("namespace") or "default")
        service_name = str(_metadata(endpoint).get("name") or "").strip()
        service_ref = _resource_ref("service", namespace, service_name)
        for subset in endpoint.get("subsets", []) or []:
            for address in [*(subset.get("addresses") or []), *(subset.get("notReadyAddresses") or [])]:
                target = address.get("targetRef") if isinstance(address, dict) else {}
                if isinstance(target, dict) and target.get("kind") == "Pod" and target.get("name"):
                    _add_topology_edge(
                        edges,
                        edge_keys,
                        service_ref,
                        _resource_ref("pod", namespace, str(target["name"])),
                        "backs_service",
                    )

    for ingress in resources.get("ingresses", []):
        meta = _metadata(ingress)
        namespace = str(meta.get("namespace") or "default")
        name = str(meta.get("name") or "").strip()
        if not name:
            continue
        ref = _resource_ref("ingress", namespace, name)
        _add_topology_node(
            nodes,
            {
                "ref": ref,
                "type": "ingress",
                "label": name,
                "namespace": namespace,
                "attributes": {"type": _spec(ingress).get("ingressClassName")},
            },
        )
        _add_topology_edge(edges, edge_keys, ref, _resource_ref("namespace", None, namespace), "in_namespace")
        for rule in _spec(ingress).get("rules", []) or []:
            host = str(rule.get("host") or "").strip()
            for path in ((rule.get("http") or {}).get("paths") or []):
                service = ((path.get("backend") or {}).get("service") or {}).get("name")
                if service:
                    route_label = host or str(path.get("path") or "routes")
                    _add_topology_edge(
                        edges,
                        edge_keys,
                        ref,
                        _resource_ref("service", namespace, str(service)),
                        "routes_to",
                        label=route_label,
                    )

    for pvc in resources.get("pvcs", []):
        meta = _metadata(pvc)
        namespace = str(meta.get("namespace") or "default")
        name = str(meta.get("name") or "").strip()
        if not name:
            continue
        _add_topology_node(
            nodes,
            {
                "ref": _resource_ref("persistent_volume_claim", namespace, name),
                "type": "persistent_volume_claim",
                "label": name,
                "namespace": namespace,
                "attributes": {
                    "phase": _status(pvc).get("phase"),
                    "storage_class": _spec(pvc).get("storageClassName"),
                    "requested": ((_spec(pvc).get("resources") or {}).get("requests") or {}).get("storage"),
                },
            },
        )

    for policy in resources.get("networkpolicies", []):
        meta = _metadata(policy)
        spec = _spec(policy)
        namespace = str(meta.get("namespace") or "default")
        name = str(meta.get("name") or "").strip()
        if not name:
            continue
        ref = _resource_ref("network_policy", namespace, name)
        _add_topology_node(
            nodes,
            {
                "ref": ref,
                "type": "network_policy",
                "label": name,
                "namespace": namespace,
                "attributes": {
                    "policy_types": spec.get("policyTypes", []),
                    "ingress_rules": len(spec.get("ingress", []) or []),
                    "egress_rules": len(spec.get("egress", []) or []),
                },
            },
        )
        _add_topology_edge(edges, edge_keys, ref, _resource_ref("namespace", None, namespace), "in_namespace")
        for pod in pods_by_namespace.get(namespace, []):
            if _selector_matches(spec.get("podSelector"), _labels(pod), empty_matches_all=True):
                _add_topology_edge(
                    edges,
                    edge_keys,
                    ref,
                    _resource_ref("pod", namespace, str(_metadata(pod).get("name") or "")),
                    "selects_pod",
                )

    ordered_nodes = sorted(
        nodes.values(),
        key=lambda node: (
            _TOPOLOGY_NODE_PRIORITY.get(str(node.get("type") or ""), 100),
            str(node.get("namespace") or ""),
            str(node.get("label") or ""),
        ),
    )
    selected_nodes = ordered_nodes[: max(1, max_nodes)]
    selected_refs = {str(node.get("ref") or "") for node in selected_nodes}
    selected_edges = [
        edge
        for edge in edges
        if str(edge.get("source_ref") or "") in selected_refs and str(edge.get("target_ref") or "") in selected_refs
    ]
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


class KubernetesTopologySnapshotTool:
    name = "kubernetes_topology_snapshot"
    description = (
        "Collect a bounded Kubernetes topology graph with resources, relationships and a draw.io diagram brief"
    )

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        _warn_if_tls_disabled(context, "kubernetes_topology_snapshot")
        namespace = str(params.get("namespace") or context.project_config.get("k8s_namespace") or "").strip() or None
        all_namespaces = _as_bool(params.get("all_namespaces"), True)
        diagram_detail = str(params.get("diagram_detail") or "full").strip().lower() or "full"
        max_nodes = max(1, min(int(params.get("max_nodes") or 1000), 5000))
        max_items = max(1, min(int(params.get("max_items") or 1000), 5000))
        if _should_use_kubectl(context):
            return await self._snapshot_with_kubectl(
                context,
                namespace=namespace,
                all_namespaces=all_namespaces,
                diagram_detail=diagram_detail,
                max_nodes=max_nodes,
                max_items=max_items,
            )
        return await self._snapshot_with_api(
            context,
            namespace=namespace,
            all_namespaces=all_namespaces,
            diagram_detail=diagram_detail,
            max_nodes=max_nodes,
            max_items=max_items,
        )

    async def _snapshot_with_kubectl(
        self,
        context: ToolContext,
        *,
        namespace: str | None,
        all_namespaces: bool,
        diagram_detail: str,
        max_nodes: int,
        max_items: int,
    ) -> dict[str, Any]:
        resources: dict[str, list[dict[str, Any]]] = {}
        warnings: list[str] = []
        for key, kind in [
            ("namespaces", "namespaces"),
            ("nodes", "nodes"),
            *[(key, api_kind[2]) for key, api_kind in _TOPOLOGY_NAMESPACED_KINDS.items()],
        ]:
            args = ["get", kind, "-o", "json"]
            if key in _TOPOLOGY_NAMESPACED_KINDS:
                if all_namespaces:
                    args.append("-A")
                elif namespace:
                    args.extend(["-n", namespace])
            returncode, stdout, _ = await _run_kubectl(context, args, timeout_sec=45)
            if returncode != 0:
                warnings.append(f"Could not collect {kind}: kubectl_command_failed exit_code={returncode}")
                resources[key] = []
                continue
            try:
                items = json.loads(stdout or "{}").get("items", [])
            except json.JSONDecodeError:
                warnings.append(f"Could not parse kubectl JSON for {kind}")
                items = []
            resources[key] = items[:max_items]
        result = build_kubernetes_topology_snapshot_from_resources(
            resources,
            source="kubectl",
            scope={"namespace": namespace, "all_namespaces": all_namespaces},
            diagram_detail=diagram_detail,
            max_nodes=max_nodes,
        )
        if warnings:
            result["warnings"] = warnings[:20]
        return result

    async def _snapshot_with_api(
        self,
        context: ToolContext,
        *,
        namespace: str | None,
        all_namespaces: bool,
        diagram_detail: str,
        max_nodes: int,
        max_items: int,
    ) -> dict[str, Any]:
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL, service account, kubeconfig, or kubectl context configured"}
        resources: dict[str, list[dict[str, Any]]] = {}
        warnings: list[str] = []
        async with httpx.AsyncClient(timeout=45, transport=_k8s_transport(verify)) as client:
            resources["namespaces"] = await self._api_items(client, f"{k8s_api}/api/v1/namespaces", headers, warnings)
            resources["nodes"] = await self._api_items(client, f"{k8s_api}/api/v1/nodes", headers, warnings)
            namespaces = [namespace] if namespace and not all_namespaces else [
                str(_metadata(ns).get("name") or "") for ns in resources["namespaces"]
            ]
            for key, (group, version, plural) in _TOPOLOGY_NAMESPACED_KINDS.items():
                items: list[dict[str, Any]] = []
                for ns in namespaces:
                    if not ns:
                        continue
                    if group:
                        url = f"{k8s_api}/apis/{group}/{version}/namespaces/{ns}/{plural}"
                    else:
                        url = f"{k8s_api}/api/{version}/namespaces/{ns}/{plural}"
                    items.extend(await self._api_items(client, url, headers, warnings))
                    if len(items) >= max_items:
                        break
                resources[key] = items[:max_items]
        result = build_kubernetes_topology_snapshot_from_resources(
            resources,
            source="api",
            scope={"namespace": namespace, "all_namespaces": all_namespaces},
            diagram_detail=diagram_detail,
            max_nodes=max_nodes,
        )
        if warnings:
            result["warnings"] = warnings[:20]
        return result

    async def _api_items(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        resp = await client.get(url, headers=headers)
        if resp.status_code in {403, 404}:
            warnings.append(f"Could not collect {url.rsplit('/', 1)[-1]}: HTTP {resp.status_code}")
            return []
        resp.raise_for_status()
        return resp.json().get("items", [])


class GetK8sEvents:
    name = "get_k8s_events"
    description = "Get Kubernetes events for a namespace or pod"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        pod = params.get("pod")

        _warn_if_tls_disabled(context, "get_k8s_events")
        if _should_use_kubectl(context):
            args = ["get", "events", "-o", "json"]
            if pod:
                args.extend(["--field-selector", f"involvedObject.name={pod}"])
            returncode, stdout, _ = await _run_kubectl(context, args, namespace=namespace)
            if returncode == 0:
                data = json.loads(stdout or "{}")
                events = data.get("items", [])
                return {
                    "source": "kubectl",
                    "namespace": namespace,
                    "pod": pod,
                    "total_events": len(events),
                    "events": [
                        {
                            "type": e.get("type"),
                            "reason": e.get("reason"),
                            "message": e.get("message"),
                            "object": e.get("involvedObject", {}).get("name"),
                            "first_seen": e.get("firstTimestamp"),
                            "last_seen": e.get("lastTimestamp"),
                            "count": e.get("count", 1),
                        }
                        for e in events
                    ],
                }
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)

        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        url = f"{k8s_api}/api/v1/namespaces/{namespace}/events"
        if pod:
            url += f"?fieldSelector=involvedObject.name={pod}"

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        events = data.get("items", [])
        return {
            "source": "api",
            "namespace": namespace,
            "pod": pod,
            "total_events": len(events),
            "events": [
                {
                    "type": e.get("type"),
                    "reason": e.get("reason"),
                    "message": e.get("message"),
                    "object": e.get("involvedObject", {}).get("name"),
                    "first_seen": e.get("firstTimestamp"),
                    "last_seen": e.get("lastTimestamp"),
                    "count": e.get("count", 1),
                }
                for e in events
            ],
        }


class GetPodLogs:
    name = "get_pod_logs"
    description = "Get logs from a specific Kubernetes pod"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        pod = params["pod"]
        container = params.get("container")
        tail_lines = params.get("tail_lines", 100)

        _warn_if_tls_disabled(context, "get_pod_logs")
        if _should_use_kubectl(context):
            args = ["logs", pod, "--tail", str(tail_lines)]
            if container:
                args.extend(["-c", container])
            returncode, stdout, _ = await _run_kubectl(context, args, timeout_sec=60, namespace=namespace)
            if returncode == 0:
                return {
                    "source": "kubectl",
                    "namespace": namespace,
                    "pod": pod,
                    "container": container,
                    "tail_lines": tail_lines,
                    "logs": redact_process_output(stdout),
                }
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)

        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        url = f"{k8s_api}/api/v1/namespaces/{namespace}/pods/{pod}/log"
        query_params = {"tailLines": tail_lines}
        if container:
            query_params["container"] = container

        async with httpx.AsyncClient(timeout=60, transport=_k8s_transport(verify)) as client:
            resp = await client.get(url, headers=headers, params=query_params)
            resp.raise_for_status()
            logs = resp.text

        return {
            "source": "api",
            "namespace": namespace,
            "pod": pod,
            "container": container,
            "tail_lines": tail_lines,
            "logs": logs,
        }


class ListFailedPods:
    name = "list_failed_pods"
    description = "List pods in failed, CrashLoop, or error state"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]

        _warn_if_tls_disabled(context, "list_failed_pods")
        if _should_use_kubectl(context):
            returncode, stdout, _ = await _run_kubectl(context, ["get", "pods", "-o", "json"], namespace=namespace)
            if returncode == 0:
                data = json.loads(stdout or "{}")
                return self._build_failed_pod_response(data, namespace, source="kubectl")
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)

        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/api/v1/namespaces/{namespace}/pods", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._build_failed_pod_response(data, namespace, source="api")

    def _build_failed_pod_response(self, data: dict, namespace: str, *, source: str) -> dict[str, Any]:
        failed = []
        for pod in data.get("items", []):
            pod_name = pod["metadata"]["name"]
            phase = pod.get("status", {}).get("phase")
            container_statuses = pod.get("status", {}).get("containerStatuses", [])

            for cs in container_statuses:
                state = cs.get("state", {})
                waiting = state.get("waiting", {})
                reason = waiting.get("reason", "")

                if phase in ("Failed", "Unknown") or reason in (
                    "CrashLoopBackOff",
                    "ImagePullBackOff",
                    "ErrImagePull",
                    "Error",
                    "OOMKilled",
                    "CreateContainerConfigError",
                ):
                    failed.append(
                        {
                            "pod": pod_name,
                            "phase": phase,
                            "reason": reason,
                            "message": waiting.get("message", ""),
                            "restart_count": cs.get("restartCount", 0),
                            "container": cs.get("name"),
                        }
                    )

        return {
            "source": source,
            "namespace": namespace,
            "total_pods": len(data.get("items", [])),
            "failed_count": len(failed),
            "failed_pods": failed,
        }


class GetK8sDeployments:
    name = "get_k8s_deployments"
    description = "Get deployment status in a namespace"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]

        _warn_if_tls_disabled(context, "get_k8s_deployments")
        if _should_use_kubectl(context):
            returncode, stdout, _ = await _run_kubectl(
                context, ["get", "deployments", "-o", "json"], namespace=namespace
            )
            if returncode == 0:
                data = json.loads(stdout or "{}")
                return self._build_response(data, namespace, source="kubectl")
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)

        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/apis/apps/v1/namespaces/{namespace}/deployments", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._build_response(data, namespace, source="api")

    def _build_response(self, data: dict, namespace: str, *, source: str) -> dict[str, Any]:
        deployments = []
        for dep in data.get("items", []):
            spec = dep.get("spec", {})
            status = dep.get("status", {})
            deployments.append(
                {
                    "name": dep["metadata"]["name"],
                    "replicas": spec.get("replicas", 0),
                    "ready_replicas": status.get("readyReplicas", 0),
                    "available_replicas": status.get("availableReplicas", 0),
                    "updated_replicas": status.get("updatedReplicas", 0),
                    "conditions": [
                        {"type": c["type"], "status": c["status"], "reason": c.get("reason")}
                        for c in status.get("conditions", [])
                    ],
                }
            )

        return {
            "source": source,
            "namespace": namespace,
            "total": len(deployments),
            "deployments": deployments,
        }


class ListNamespaces:
    name = "list_k8s_namespaces"
    description = "List all namespaces in the cluster"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        _warn_if_tls_disabled(context, "list_k8s_namespaces")
        if _should_use_kubectl(context):
            returncode, stdout, _ = await _run_kubectl(context, ["get", "namespaces", "-o", "json"])
            if returncode == 0:
                data = json.loads(stdout or "{}")
                return self._build_response(data, source="kubectl")
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/api/v1/namespaces", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._build_response(data, source="api")

    def _build_response(self, data: dict, *, source: str) -> dict[str, Any]:
        namespaces = []
        for ns in data.get("items", []):
            namespaces.append({
                "name": ns["metadata"]["name"],
                "status": ns.get("status", {}).get("phase"),
                "labels": ns.get("metadata", {}).get("labels", {}),
            })
        return {"source": source, "total": len(namespaces), "namespaces": namespaces}


class ListPods:
    name = "list_k8s_pods"
    description = "List all pods in a namespace with their status, restarts and age"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        label_selector = params.get("label_selector")

        _warn_if_tls_disabled(context, "list_k8s_pods")
        if _should_use_kubectl(context):
            args = ["get", "pods", "-o", "json"]
            if label_selector:
                args.extend(["-l", label_selector])
            returncode, stdout, _ = await _run_kubectl(context, args, namespace=namespace)
            if returncode == 0:
                data = json.loads(stdout or "{}")
                return self._build_response(data, namespace, source="kubectl")
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        url = f"{k8s_api}/api/v1/namespaces/{namespace}/pods"
        qparams: dict[str, str] = {}
        if label_selector:
            qparams["labelSelector"] = label_selector

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(url, headers=headers, params=qparams)
            resp.raise_for_status()
            data = resp.json()

        return self._build_response(data, namespace, source="api")

    def _build_response(self, data: dict, namespace: str, *, source: str) -> dict[str, Any]:
        pods = []
        for pod in data.get("items", []):
            status = pod.get("status", {})
            container_statuses = status.get("containerStatuses", [])
            total_restarts = sum(cs.get("restartCount", 0) for cs in container_statuses)
            ready = sum(1 for cs in container_statuses if cs.get("ready"))
            total = len(container_statuses) or len(pod.get("spec", {}).get("containers", []))
            pods.append({
                "name": pod["metadata"]["name"],
                "namespace": namespace,
                "phase": status.get("phase"),
                "ready": f"{ready}/{total}",
                "restarts": total_restarts,
                "node": pod.get("spec", {}).get("nodeName"),
                "start_time": status.get("startTime"),
                "containers": [cs.get("name") for cs in container_statuses],
            })
        return {"source": source, "namespace": namespace, "total": len(pods), "pods": pods}


class DescribePod:
    name = "describe_k8s_pod"
    description = "Get detailed information about a specific pod including conditions, containers, volumes and events"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        pod_name = params["pod"]

        _warn_if_tls_disabled(context, "describe_k8s_pod")
        if _should_use_kubectl(context):
            returncode, stdout, _ = await _run_kubectl(
                context, ["get", "pod", pod_name, "-o", "json"], namespace=namespace
            )
            if returncode == 0:
                data = json.loads(stdout or "{}")
                return self._build_response(data, source="kubectl")
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/api/v1/namespaces/{namespace}/pods/{pod_name}", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._build_response(data, source="api")

    def _build_response(self, pod: dict, *, source: str) -> dict[str, Any]:
        meta = pod.get("metadata", {})
        spec = pod.get("spec", {})
        status = pod.get("status", {})
        containers = []
        for c in spec.get("containers", []):
            cs = next((s for s in status.get("containerStatuses", []) if s.get("name") == c["name"]), {})
            state_info = {}
            for state_key in ("running", "waiting", "terminated"):
                if state_key in cs.get("state", {}):
                    state_info = {"state": state_key, **cs["state"][state_key]}
                    break
            res = c.get("resources", {})
            containers.append({
                "name": c["name"],
                "image": c.get("image"),
                "ready": cs.get("ready", False),
                "restart_count": cs.get("restartCount", 0),
                "state": state_info,
                "requests": res.get("requests"),
                "limits": res.get("limits"),
            })
        return {
            "source": source,
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "node": spec.get("nodeName"),
            "service_account": spec.get("serviceAccountName"),
            "phase": status.get("phase"),
            "start_time": status.get("startTime"),
            "conditions": [
                {"type": c["type"], "status": c["status"], "reason": c.get("reason"), "message": c.get("message")}
                for c in status.get("conditions", [])
            ],
            "containers": containers,
            "labels": meta.get("labels", {}),
            "annotations_count": len(meta.get("annotations", {})),
        }


class ListServices:
    name = "list_k8s_services"
    description = "List services in a namespace with their type, cluster IP, ports and selectors"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]

        _warn_if_tls_disabled(context, "list_k8s_services")
        if _should_use_kubectl(context):
            returncode, stdout, _ = await _run_kubectl(
                context, ["get", "services", "-o", "json"], namespace=namespace
            )
            if returncode == 0:
                data = json.loads(stdout or "{}")
                return self._build_response(data, namespace, source="kubectl")
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/api/v1/namespaces/{namespace}/services", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._build_response(data, namespace, source="api")

    def _build_response(self, data: dict, namespace: str, *, source: str) -> dict[str, Any]:
        services = []
        for svc in data.get("items", []):
            spec = svc.get("spec", {})
            ports = [
                {
                    "port": p.get("port"),
                    "target_port": p.get("targetPort"),
                    "protocol": p.get("protocol"),
                    "name": p.get("name"),
                }
                for p in spec.get("ports", [])
            ]
            services.append({
                "name": svc["metadata"]["name"],
                "type": spec.get("type"),
                "cluster_ip": spec.get("clusterIP"),
                "external_ip": spec.get("externalIPs", []) or spec.get("loadBalancerIP"),
                "ports": ports,
                "selector": spec.get("selector"),
            })
        return {"source": source, "namespace": namespace, "total": len(services), "services": services}


class ListNodes:
    name = "list_k8s_nodes"
    description = "List cluster nodes with their status, roles, capacity and resource usage"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        _warn_if_tls_disabled(context, "list_k8s_nodes")
        if _should_use_kubectl(context):
            returncode, stdout, _ = await _run_kubectl(context, ["get", "nodes", "-o", "json"])
            if returncode == 0:
                data = json.loads(stdout or "{}")
                return self._build_response(data, source="kubectl")
            if not context.project_config.get("k8s_api_url") and not _SA_TOKEN_PATH.exists():
                return _kubectl_failure(returncode)

        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/api/v1/nodes", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._build_response(data, source="api")

    def _build_response(self, data: dict, *, source: str) -> dict[str, Any]:
        nodes = []
        for node in data.get("items", []):
            meta = node.get("metadata", {})
            status = node.get("status", {})
            conditions = status.get("conditions", [])
            ready_cond = next((c for c in conditions if c["type"] == "Ready"), {})
            labels = meta.get("labels", {})
            capacity = status.get("capacity", {})
            allocatable = status.get("allocatable", {})
            roles = [
                k.replace("node-role.kubernetes.io/", "")
                for k in labels
                if k.startswith("node-role.kubernetes.io/")
            ]
            nodes.append({
                "name": meta.get("name"),
                "roles": roles or ["<none>"],
                "ready": ready_cond.get("status") == "True",
                "nodegroup": labels.get("eks.amazonaws.com/nodegroup", ""),
                "instance_type": labels.get("node.kubernetes.io/instance-type", ""),
                "os": labels.get("kubernetes.io/os", ""),
                "arch": labels.get("kubernetes.io/arch", ""),
                "capacity_cpu": capacity.get("cpu"),
                "capacity_memory": capacity.get("memory"),
                "allocatable_cpu": allocatable.get("cpu"),
                "allocatable_memory": allocatable.get("memory"),
                "conditions": [
                    {"type": c["type"], "status": c["status"], "reason": c.get("reason")}
                    for c in conditions if c.get("status") != "False"
                ],
            })
        return {"source": source, "total": len(nodes), "nodes": nodes}


class GetConfigMap:
    name = "get_k8s_configmap"
    description = "Get a ConfigMap's data by name, or list all ConfigMaps in a namespace"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        name = params.get("name")

        _warn_if_tls_disabled(context, "get_k8s_configmap")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            if name:
                resp = await client.get(f"{k8s_api}/api/v1/namespaces/{namespace}/configmaps/{name}", headers=headers)
                resp.raise_for_status()
                cm = resp.json()
                return {
                    "source": "api", "name": name, "namespace": namespace,
                    # Keys only: a ConfigMap can hold secrets, and the tool runs with the API's credentials.
                    "data_keys": list((cm.get("data") or {}).keys()),
                }
            else:
                resp = await client.get(f"{k8s_api}/api/v1/namespaces/{namespace}/configmaps", headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return {
                    "source": "api", "namespace": namespace,
                    "total": len(data.get("items", [])),
                    "configmaps": [
                        {"name": cm["metadata"]["name"], "data_keys": list((cm.get("data") or {}).keys())}
                        for cm in data.get("items", [])
                    ],
                }


class ListIngresses:
    name = "list_k8s_ingresses"
    description = "List ingresses in a namespace with their hosts, paths and backends"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]

        _warn_if_tls_disabled(context, "list_k8s_ingresses")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(
                f"{k8s_api}/apis/networking.k8s.io/v1/namespaces/{namespace}/ingresses",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        ingresses = []
        for ing in data.get("items", []):
            spec = ing.get("spec", {})
            rules = []
            for rule in spec.get("rules", []):
                paths = []
                for p in rule.get("http", {}).get("paths", []):
                    backend = p.get("backend", {})
                    svc = backend.get("service", {})
                    paths.append({
                        "path": p.get("path"),
                        "path_type": p.get("pathType"),
                        "service": svc.get("name"),
                        "port": svc.get("port", {}).get("number") or svc.get("port", {}).get("name"),
                    })
                rules.append({"host": rule.get("host"), "paths": paths})
            ingresses.append({
                "name": ing["metadata"]["name"],
                "class": spec.get("ingressClassName"),
                "rules": rules,
                "tls": [{"hosts": t.get("hosts", []), "secret": t.get("secretName")} for t in spec.get("tls", [])],
            })
        return {"source": "api", "namespace": namespace, "total": len(ingresses), "ingresses": ingresses}


class GetResourceUsage:
    name = "get_k8s_resource_usage"
    description = "Get CPU and memory usage of pods in a namespace from the metrics API"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]

        _warn_if_tls_disabled(context, "get_k8s_resource_usage")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(
                f"{k8s_api}/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods",
                headers=headers,
            )
            if resp.status_code == 404:
                return {"error": "Metrics API not available. Ensure metrics-server is installed."}
            resp.raise_for_status()
            data = resp.json()

        pods = []
        for pod in data.get("items", []):
            containers = []
            for c in pod.get("containers", []):
                containers.append({
                    "name": c.get("name"),
                    "cpu": c.get("usage", {}).get("cpu"),
                    "memory": c.get("usage", {}).get("memory"),
                })
            pods.append({
                "name": pod["metadata"]["name"],
                "namespace": namespace,
                "containers": containers,
            })
        return {"source": "api", "namespace": namespace, "total": len(pods), "pods": pods}


class DescribeDeployment:
    name = "describe_k8s_deployment"
    description = "Get detailed deployment info: strategy, conditions, rollout status, replicas, pod template"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        name = params["name"]
        _warn_if_tls_disabled(context, "describe_k8s_deployment")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(
                f"{k8s_api}/apis/apps/v1/namespaces/{namespace}/deployments/{name}", headers=headers
            )
            resp.raise_for_status()
            dep = resp.json()

        meta = dep.get("metadata", {})
        spec = dep.get("spec", {})
        status = dep.get("status", {})
        strategy = spec.get("strategy", {})
        tmpl = spec.get("template", {}).get("spec", {})
        containers = []
        for c in tmpl.get("containers", []):
            res = c.get("resources", {})
            containers.append({
                "name": c["name"],
                "image": c.get("image"),
                "requests": res.get("requests"),
                "limits": res.get("limits"),
                "env_count": len(c.get("env", [])),
                "volume_mounts": [vm.get("name") for vm in c.get("volumeMounts", [])],
            })
        return {
            "source": "api", "name": meta.get("name"), "namespace": namespace,
            "replicas": spec.get("replicas"),
            "ready": status.get("readyReplicas", 0), "available": status.get("availableReplicas", 0),
            "updated": status.get("updatedReplicas", 0),
            "strategy": {"type": strategy.get("type"), **strategy.get("rollingUpdate", {})},
            "conditions": [
                {"type": c["type"], "status": c["status"], "reason": c.get("reason"), "message": c.get("message")}
                for c in status.get("conditions", [])
            ],
            "containers": containers,
            "service_account": tmpl.get("serviceAccountName"),
            "node_selector": tmpl.get("nodeSelector"),
            "tolerations": tmpl.get("tolerations"),
            "labels": meta.get("labels", {}),
            "selector": spec.get("selector", {}).get("matchLabels", {}),
        }


class DescribeNode:
    name = "describe_k8s_node"
    description = "Get detailed node info: conditions, addresses, capacity, allocatable, system info, taints"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        node_name = params["node"]
        _warn_if_tls_disabled(context, "describe_k8s_node")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/api/v1/nodes/{node_name}", headers=headers)
            resp.raise_for_status()
            node = resp.json()

        meta = node.get("metadata", {})
        status = node.get("status", {})
        spec = node.get("spec", {})
        labels = meta.get("labels", {})
        return {
            "source": "api", "name": meta.get("name"),
            "roles": [
                k.replace("node-role.kubernetes.io/", "")
                for k in labels
                if k.startswith("node-role.kubernetes.io/")
            ] or ["<none>"],
            "nodegroup": labels.get("eks.amazonaws.com/nodegroup", ""),
            "instance_type": labels.get("node.kubernetes.io/instance-type", ""),
            "zone": labels.get("topology.kubernetes.io/zone", ""),
            "os": f"{labels.get('kubernetes.io/os', '')} {labels.get('kubernetes.io/arch', '')}",
            "kubelet_version": status.get("nodeInfo", {}).get("kubeletVersion"),
            "container_runtime": status.get("nodeInfo", {}).get("containerRuntimeVersion"),
            "capacity": status.get("capacity", {}),
            "allocatable": status.get("allocatable", {}),
            "conditions": [
                {"type": c["type"], "status": c["status"], "reason": c.get("reason"), "message": c.get("message")}
                for c in status.get("conditions", [])
            ],
            "addresses": [{"type": a["type"], "address": a["address"]} for a in status.get("addresses", [])],
            "taints": spec.get("taints", []),
            "unschedulable": spec.get("unschedulable", False),
        }


class ListStatefulSets:
    name = "list_k8s_statefulsets"
    description = "List StatefulSets in a namespace with their replicas and status"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_statefulsets")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/apis/apps/v1/namespaces/{namespace}/statefulsets", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = []
        for ss in data.get("items", []):
            status = ss.get("status", {})
            spec = ss.get("spec", {})
            items.append({
                "name": ss["metadata"]["name"],
                "replicas": spec.get("replicas"),
                "ready": status.get("readyReplicas", 0),
                "current": status.get("currentReplicas", 0),
                "updated": status.get("updatedReplicas", 0),
                "service_name": spec.get("serviceName"),
                "update_strategy": spec.get("updateStrategy", {}).get("type"),
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "statefulsets": items}


class ListDaemonSets:
    name = "list_k8s_daemonsets"
    description = "List DaemonSets in a namespace with their desired/ready counts"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_daemonsets")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/apis/apps/v1/namespaces/{namespace}/daemonsets", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = []
        for ds in data.get("items", []):
            status = ds.get("status", {})
            items.append({
                "name": ds["metadata"]["name"],
                "desired": status.get("desiredNumberScheduled", 0),
                "ready": status.get("numberReady", 0),
                "available": status.get("numberAvailable", 0),
                "misscheduled": status.get("numberMisscheduled", 0),
                "node_selector": ds.get("spec", {}).get("template", {}).get("spec", {}).get("nodeSelector"),
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "daemonsets": items}


class ListJobs:
    name = "list_k8s_jobs"
    description = "List Jobs in a namespace with their completion status and duration"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_jobs")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/apis/batch/v1/namespaces/{namespace}/jobs", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = []
        for job in data.get("items", []):
            status = job.get("status", {})
            conditions = status.get("conditions", [])
            condition_types = [c["type"] for c in conditions if c.get("status") == "True"]
            items.append({
                "name": job["metadata"]["name"],
                "completions": job.get("spec", {}).get("completions"),
                "succeeded": status.get("succeeded", 0),
                "failed": status.get("failed", 0),
                "active": status.get("active", 0),
                "start_time": status.get("startTime"),
                "completion_time": status.get("completionTime"),
                "conditions": condition_types,
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "jobs": items}


class ListCronJobs:
    name = "list_k8s_cronjobs"
    description = "List CronJobs in a namespace with schedule, last run and suspend status"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_cronjobs")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/apis/batch/v1/namespaces/{namespace}/cronjobs", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = []
        for cj in data.get("items", []):
            spec = cj.get("spec", {})
            status = cj.get("status", {})
            items.append({
                "name": cj["metadata"]["name"],
                "schedule": spec.get("schedule"),
                "suspend": spec.get("suspend", False),
                "concurrency_policy": spec.get("concurrencyPolicy"),
                "last_schedule_time": status.get("lastScheduleTime"),
                "last_successful_time": status.get("lastSuccessfulTime"),
                "active_jobs": len(status.get("active", [])),
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "cronjobs": items}


class ListPVCs:
    name = "list_k8s_pvcs"
    description = "List PersistentVolumeClaims in a namespace with capacity, access modes and bound status"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_pvcs")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/api/v1/namespaces/{namespace}/persistentvolumeclaims", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = []
        for pvc in data.get("items", []):
            spec = pvc.get("spec", {})
            status = pvc.get("status", {})
            items.append({
                "name": pvc["metadata"]["name"],
                "phase": status.get("phase"),
                "access_modes": spec.get("accessModes", []),
                "storage_class": spec.get("storageClassName"),
                "requested": spec.get("resources", {}).get("requests", {}).get("storage"),
                "capacity": status.get("capacity", {}).get("storage"),
                "volume_name": spec.get("volumeName"),
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "pvcs": items}


class ListEndpoints:
    name = "list_k8s_endpoints"
    description = "List Endpoints in a namespace to check service-to-pod connectivity and readiness"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        service_name = params.get("service")
        _warn_if_tls_disabled(context, "list_k8s_endpoints")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            if service_name:
                resp = await client.get(
                    f"{k8s_api}/api/v1/namespaces/{namespace}/endpoints/{service_name}",
                    headers=headers,
                )
                resp.raise_for_status()
                ep_list = [resp.json()]
            else:
                resp = await client.get(f"{k8s_api}/api/v1/namespaces/{namespace}/endpoints", headers=headers)
                resp.raise_for_status()
                ep_list = resp.json().get("items", [])

        endpoints = []
        for ep in ep_list:
            subsets = ep.get("subsets", [])
            ready_addrs = []
            not_ready_addrs = []
            ports = []
            for subset in subsets:
                for addr in subset.get("addresses", []):
                    target = addr.get("targetRef", {})
                    ready_addrs.append({"ip": addr["ip"], "pod": target.get("name"), "node": addr.get("nodeName")})
                for addr in subset.get("notReadyAddresses", []):
                    target = addr.get("targetRef", {})
                    not_ready_addrs.append({"ip": addr["ip"], "pod": target.get("name"), "node": addr.get("nodeName")})
                for port in subset.get("ports", []):
                    ports.append({"port": port.get("port"), "protocol": port.get("protocol"), "name": port.get("name")})
            endpoints.append({
                "name": ep["metadata"]["name"],
                "ready_addresses": ready_addrs,
                "not_ready_addresses": not_ready_addrs,
                "ports": ports,
            })
        return {"source": "api", "namespace": namespace, "total": len(endpoints), "endpoints": endpoints}


class ListNetworkPolicies:
    name = "list_k8s_network_policies"
    description = "List NetworkPolicies in a namespace with their pod selectors, ingress and egress rules"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_network_policies")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(
                f"{k8s_api}/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies", headers=headers
            )
            resp.raise_for_status()
            data = resp.json()

        policies = []
        for np in data.get("items", []):
            spec = np.get("spec", {})
            policies.append({
                "name": np["metadata"]["name"],
                "pod_selector": spec.get("podSelector", {}),
                "policy_types": spec.get("policyTypes", []),
                "ingress_rules": len(spec.get("ingress", [])),
                "egress_rules": len(spec.get("egress", [])),
                "ingress": spec.get("ingress", []),
                "egress": spec.get("egress", []),
            })
        return {"source": "api", "namespace": namespace, "total": len(policies), "network_policies": policies}


class ListHPAs:
    name = "list_k8s_hpas"
    description = "List HorizontalPodAutoscalers in a namespace with current/target metrics and replica counts"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_hpas")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(
                f"{k8s_api}/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers", headers=headers
            )
            if resp.status_code == 404:
                resp = await client.get(
                    f"{k8s_api}/apis/autoscaling/v1/namespaces/{namespace}/horizontalpodautoscalers", headers=headers
                )
            resp.raise_for_status()
            data = resp.json()

        items = []
        for hpa in data.get("items", []):
            spec = hpa.get("spec", {})
            status = hpa.get("status", {})
            metrics_spec = spec.get("metrics", [])
            current_metrics = status.get("currentMetrics", [])
            items.append({
                "name": hpa["metadata"]["name"],
                "target": f"{spec.get('scaleTargetRef', {}).get('kind')}/{spec.get('scaleTargetRef', {}).get('name')}",
                "min_replicas": spec.get("minReplicas"),
                "max_replicas": spec.get("maxReplicas"),
                "current_replicas": status.get("currentReplicas"),
                "desired_replicas": status.get("desiredReplicas"),
                "metrics_count": len(metrics_spec),
                "current_metrics_count": len(current_metrics),
                "conditions": [
                    {"type": c["type"], "status": c["status"], "reason": c.get("reason")}
                    for c in status.get("conditions", [])
                ],
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "hpas": items}


class ListSecrets:
    name = "list_k8s_secrets"
    description = "List Secrets in a namespace (metadata only - names, types, creation dates, no values)"

    @_alert_scoped
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        namespace = params["namespace"]
        _warn_if_tls_disabled(context, "list_k8s_secrets")
        k8s_api, headers, verify = _resolve_k8s_api_config(context)
        if not k8s_api:
            return {"error": "No Kubernetes API URL configured for this project"}

        async with httpx.AsyncClient(timeout=30, transport=_k8s_transport(verify)) as client:
            resp = await client.get(f"{k8s_api}/api/v1/namespaces/{namespace}/secrets", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = []
        for secret in data.get("items", []):
            meta = secret.get("metadata", {})
            items.append({
                "name": meta.get("name"),
                "type": secret.get("type"),
                "data_keys": list((secret.get("data") or {}).keys()),
                "created": meta.get("creationTimestamp"),
            })
        return {"source": "api", "namespace": namespace, "total": len(items), "secrets": items}


