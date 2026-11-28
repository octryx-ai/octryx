"""The kubernetes_topology_snapshot tool: lists the cluster's resources and builds their topology."""

import json
from typing import Any

import httpx

from .context import ToolContext
from .kubernetes import (
    _alert_scoped,
    _as_bool,
    _k8s_transport,
    _resolve_k8s_api_config,
    _run_kubectl,
    _should_use_kubectl,
    _warn_if_tls_disabled,
)
from .kubernetes_topology import _metadata, build_kubernetes_topology_snapshot_from_resources

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
