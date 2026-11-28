"""Kubernetes cluster tools: namespaces, nodes, resource usage and events."""

import json
from typing import Any

import httpx

from .context import ToolContext
from .kubernetes import (
    _SA_TOKEN_PATH,
    _alert_scoped,
    _k8s_transport,
    _kubectl_failure,
    _resolve_k8s_api_config,
    _run_kubectl,
    _should_use_kubectl,
    _warn_if_tls_disabled,
)


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
