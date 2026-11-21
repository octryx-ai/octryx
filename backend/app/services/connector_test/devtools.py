from __future__ import annotations

import base64
from typing import Any

from app.services.outbound_egress import (
    CONNECTION_AZURE_DEVOPS,
    CONNECTION_CONTAINER_REGISTRY,
    CONNECTION_LINEAR,
    egress_transport,
)

from .failure import connection_success, http_status_failure


async def test_docker_registry_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    base_url = str(config.get("docker_registry_url") or "").strip().rstrip("/")
    provider = str(config.get("docker_registry_provider") or "").strip().lower() or "registry"
    username = str(config.get("docker_registry_username") or "").strip()
    password = str(config.get("docker_registry_password") or "").strip()
    if not base_url:
        return {"ok": False, "summary": "docker_registry_url is required."}
    auth = (username, password) if username and password else None
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_CONTAINER_REGISTRY)
    ) as client:
        if provider == "harbor":
            response = await client.get(
                f"{base_url}/api/v2.0/systeminfo",
                auth=auth,
                headers={"Accept": "application/json"},
            )
            if response.status_code >= 400:
                return http_status_failure("Harbor", response.status_code)
            payload = response.json()
            return connection_success("Connected to Harbor.", version=payload.get("harbor_version"))
        response = await client.get(
            f"{base_url}/v2/",
            auth=auth,
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        return http_status_failure("Docker Registry", response.status_code)
    return connection_success("Connected to Docker Registry.")


async def test_linear_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    linear_url = str(config.get("linear_url") or "https://api.linear.app/graphql").strip().rstrip("/")
    api_key = str(config.get("linear_api_key") or "").strip()
    if not linear_url:
        return {"ok": False, "summary": "linear_url is required."}
    if not api_key:
        return {"ok": False, "summary": "linear_api_key is required."}
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_LINEAR)
    ) as client:
        response = await client.post(
            linear_url,
            headers=headers,
            json={"query": "query { viewer { id name } }"},
        )
    if response.status_code >= 400:
        return http_status_failure("Linear", response.status_code)
    return connection_success("Connected to Linear.")


async def test_azure_devops_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    base_url = str(config.get("azure_devops_url") or "").strip().rstrip("/")
    pat = str(config.get("azure_devops_pat") or "").strip()
    if not base_url:
        return {"ok": False, "summary": "azure_devops_url is required."}
    if not pat:
        return {"ok": False, "summary": "azure_devops_pat is required."}
    token = base64.b64encode(f":{pat}".encode()).decode("ascii")
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_AZURE_DEVOPS)
    ) as client:
        response = await client.get(
            f"{base_url}/_apis/projects",
            headers=headers,
            params={"api-version": "7.1"},
        )
    if response.status_code >= 400:
        return http_status_failure("Azure DevOps", response.status_code)
    payload = response.json()
    projects = payload.get("count") or len(payload.get("value") or [])
    return connection_success("Connected to Azure DevOps.", counts={"visible_projects": projects})
