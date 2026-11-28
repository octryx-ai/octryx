"""Kubernetes network tools: services, ingresses, endpoints and network policies."""

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
