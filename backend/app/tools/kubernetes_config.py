"""Kubernetes configuration and storage tools: config maps, secrets and volume claims."""

from typing import Any

import httpx

from .context import ToolContext
from .kubernetes import _alert_scoped, _k8s_transport, _resolve_k8s_api_config, _warn_if_tls_disabled


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
