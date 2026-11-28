"""Kubernetes tool implementations."""

import functools
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_KUBERNETES, egress_transport

from ..services.execution_runtime import (
    execute_with_runtime,
    resolve_execution_runtime_config,
    workspace_mount_for_path,
)
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
    return egress_transport(CONNECTION_KUBERNETES, verify=verify)


def _warn_if_tls_disabled(context: ToolContext, source: str) -> None:
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


