"""Kubernetes pod tools: list, describe, logs and failed pods."""

import json
from typing import Any

import httpx

from ..services.process_output_redaction import redact_process_output
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
