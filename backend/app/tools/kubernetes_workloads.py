"""Kubernetes workload tools: deployments, stateful sets, daemon sets and autoscalers."""

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
