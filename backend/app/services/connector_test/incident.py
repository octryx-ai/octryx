from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.outbound_egress import (
    CONNECTION_ARGOCD,
    CONNECTION_KUBERNETES,
    CONNECTION_OPSGENIE,
    CONNECTION_PAGERDUTY,
    CONNECTION_STATUSPAGE,
    egress_transport,
)
from app.tools.context import ToolContext

from ...tools.kubernetes import _run_kubectl, _should_use_kubectl
from ...tools.kubernetes_transport import kubernetes_tls_verify
from ..run_capability.worker_profiles import worker_tool_context_state
from .failure import command_failure, connection_success, http_status_failure


def _build_health_context(config: dict[str, Any], db: Any = None) -> ToolContext:
    """The test's tool context; ``db``: the caller's session, so tool helpers resolve as in a real call."""
    return ToolContext(
        user_id="connector-health",
        project_ids=[],
        roles=["admin"],
        session_id="connector-health",
        project_config=config,
        workspace_root=str(Path.cwd()),
        run_capability=worker_tool_context_state("connector_health_check"),
        db=db,
    )


async def test_kubernetes_connection(
    config: dict[str, Any], *, httpx_module: Any, db: Any = None
) -> dict[str, Any]:
    context = _build_health_context(config, db)
    if _should_use_kubectl(context):
        returncode, stdout, _stderr = await _run_kubectl(context, ["version", "-o", "json"], timeout_sec=10)
        if returncode != 0:
            return command_failure("kubectl", returncode)
        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError:
            payload = {}
        server_version = (payload.get("serverVersion") or {}).get("gitVersion") if isinstance(payload, dict) else None
        return connection_success("kubectl connection succeeded.", version=server_version)

    k8s_api_url = str(config.get("k8s_api_url") or "").strip().rstrip("/")
    if not k8s_api_url:
        # Auto-detect in-cluster
        import os
        if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token"):
            k8s_api_url = "https://kubernetes.default.svc"
        else:
            return {
                "ok": False,
                "summary": "Configure kubeconfig/context for kubectl or set k8s_api_url for direct API access.",
            }
    headers: dict[str, str] = {}
    in_cluster_ca = None
    token = config.get("k8s_token")
    if not token:
        import pathlib
        sa_token_path = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        if sa_token_path.exists():
            token = sa_token_path.read_text().strip()
            ca_path = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
            if ca_path.exists():
                in_cluster_ca = str(ca_path)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx_module.AsyncClient(
        timeout=15, transport=egress_transport(CONNECTION_KUBERNETES,
                                                      verify=kubernetes_tls_verify(config,
                                                                                   in_cluster_ca=in_cluster_ca))
    ) as client:
        response = await client.get(f"{k8s_api_url}/version", headers=headers)
    if response.status_code >= 400:
        return http_status_failure("Kubernetes API", response.status_code)
    payload = response.json()
    return connection_success("Kubernetes API connection succeeded.", version=payload.get("gitVersion"))


async def test_pagerduty_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    provider = str(config.get("incident_provider") or "").strip().lower()
    use_opsgenie = provider == "opsgenie" or bool(config.get("opsgenie_url") or config.get("opsgenie_token"))
    if use_opsgenie:
        opsgenie_url = str(config.get("opsgenie_url") or "https://api.opsgenie.com").strip().rstrip("/")
        opsgenie_token = str(config.get("opsgenie_token") or "").strip()
        if not opsgenie_url or not opsgenie_token:
            return {
                "ok": False,
                "summary": "opsgenie_url and opsgenie_token are required for OpsGenie mode.",
            }
        async with httpx_module.AsyncClient(
            timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_OPSGENIE)
        ) as client:
            response = await client.get(
                f"{opsgenie_url}/v2/account",
                headers={"Authorization": f"GenieKey {opsgenie_token}"},
            )
        if response.status_code >= 400:
            return http_status_failure("OpsGenie", response.status_code)
        return connection_success("Connected to OpsGenie.")

    pagerduty_url = str(config.get("pagerduty_url") or "https://api.pagerduty.com").strip().rstrip("/")
    pagerduty_token = str(config.get("pagerduty_token") or "").strip()
    if not pagerduty_url or not pagerduty_token:
        return {
            "ok": False,
            "summary": "pagerduty_url and pagerduty_token are required for PagerDuty mode.",
        }
    headers = {
        "Authorization": f"Token token={pagerduty_token}",
        "Accept": "application/vnd.pagerduty+json;version=2",
    }
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_PAGERDUTY)
    ) as client:
        response = await client.get(f"{pagerduty_url}/users/me", headers=headers)
    if response.status_code >= 400:
        return http_status_failure("PagerDuty", response.status_code)
    return connection_success("Connected to PagerDuty.")


async def test_argocd_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    argocd_url = str(config.get("argocd_url") or "").strip().rstrip("/")
    argocd_token = str(config.get("argocd_token") or "").strip()
    if not argocd_url or not argocd_token:
        return {
            "ok": False,
            "summary": "argocd_url and argocd_token are required.",
        }
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_ARGOCD)
    ) as client:
        response = await client.get(
            f"{argocd_url}/api/v1/session/userinfo",
            headers={"Authorization": f"Bearer {argocd_token}", "Accept": "application/json"},
        )
    if response.status_code >= 400:
        return http_status_failure("ArgoCD", response.status_code)
    return connection_success("Connected to ArgoCD.")


async def test_statuspage_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    statuspage_url = str(config.get("statuspage_url") or "https://api.statuspage.io").strip().rstrip("/")
    api_key = str(config.get("statuspage_api_key") or "").strip()
    page_id = str(config.get("statuspage_page_id") or "").strip()
    if not statuspage_url or not api_key or not page_id:
        return {"ok": False, "summary": "statuspage_url, statuspage_api_key and statuspage_page_id are required."}
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_STATUSPAGE)
    ) as client:
        response = await client.get(
            f"{statuspage_url}/v1/pages/{page_id}",
            headers={"Authorization": f"OAuth {api_key}", "Accept": "application/json"},
        )
    if response.status_code >= 400:
        return http_status_failure("Statuspage", response.status_code)
    return connection_success("Connected to Statuspage.")
