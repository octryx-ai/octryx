"""Kubernetes: one named connection per cluster, an API URL and a token, bound to cluster (context) names.

A named connection is the API path only (``k8s_api_url`` + ``k8s_token``, optional public PEM CA and allowed
namespaces): a kubeconfig, a context or a kubectl binary picks a host credential, so none of them is inherited
from the default entry (``named_drops``) and a named connection without its token is refused before the call
(``runtime_guard``) instead of falling back to the platform pod's service account. ``run_kubectl`` runs a
kubeconfig and therefore never runs on a named connection. With allowed namespaces, a call must name one of
them; cluster-wide reads are refused on such a connection.

A call names its cluster with ``cluster``; the default entry serves the cluster of its own ``k8s_context``.
Without a cluster and with named connections, a call names its ``connection`` (``unscoped`` ``single``).
"""

from __future__ import annotations

from ....tools.kubernetes_transport import KubernetesTLSConfigurationError, kubernetes_tls_verify
from ..descriptor import (
    CASE_EXACT,
    UNSCOPED_SINGLE,
    Binding,
    ConnectorDescriptor,
    Field,
    UnitIncompleteError,
    listed_entries,
    require_fields,
)

RUN_KUBECTL = "run_kubectl"
_NAMESPACE_KEYS = ("namespace",)
_CLUSTER_WIDE = ("all_namespaces",)


def _cluster_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    cluster = params.get("cluster")
    return (cluster.strip(),) if isinstance(cluster, str) else ()


def _complete(config: dict) -> None:
    require_fields(config, "k8s_api_url", "k8s_token")
    _verified_tls(config)


def _verified_tls(config: dict) -> None:
    try:
        kubernetes_tls_verify(config)
    except KubernetesTLSConfigurationError as error:
        raise UnitIncompleteError("kubernetes_tls_not_configured", str(error)) from error


def _runtime_guard(config: dict) -> None:
    if not (str(config.get("k8s_api_url") or "").strip() and str(config.get("k8s_token") or "").strip()):
        raise UnitIncompleteError("named_connection_credential_unavailable",
                                  "its API URL or token is not available (no fallback to the platform's own).")
    _verified_tls(config)


def _request_guard(tool_name: str, config: dict, params: dict) -> str | None:
    if tool_name == RUN_KUBECTL:
        return "run_kubectl uses a kubeconfig; a named Kubernetes connection serves the Kubernetes read tools only."
    allowed = {str(item).strip() for item in listed_entries(config.get("k8s_allowed_namespaces")) if str(item).strip()}
    if not allowed:
        return None
    if any(params.get(key) is True for key in _CLUSTER_WIDE):
        return "This connection is limited to its namespaces; a call across all namespaces is refused."
    namespace = next((params.get(key) for key in _NAMESPACE_KEYS if isinstance(params.get(key), str)), "")
    if not namespace.strip():
        return "This connection is limited to its namespaces; name one of them."
    if namespace.strip() not in allowed:
        return "The namespace is not one this connection may read."
    return None


KUBERNETES = ConnectorDescriptor(
    connector="kubernetes",
    label="Kubernetes",
    binding=Binding("cluster", "Clusters", r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}", CASE_EXACT,
                    "cluster-1, cluster-2"),
    fields=(
        Field("k8s_api_url", "API server URL", kind="url", required=True,
              placeholder="https://cluster.example.com:6443"),
        Field("k8s_verify_tls", "Verify TLS", kind="bool"),
        Field("k8s_ca_certificate", "CA certificate (public PEM)", kind="text",
              placeholder="-----BEGIN CERTIFICATE----- ... -----END CERTIFICATE-----"),
        Field("k8s_allowed_namespaces", "Allowed namespaces (empty: all)", kind="list"),
        Field("k8s_token", "Service account token", kind="secret", required=True),
    ),
    usable_field="k8s_api_url",
    default_usable_fields=("kubeconfig_path", "k8s_context", "k8s_use_kubectl"),
    request_keys=_cluster_keys,
    request_params={"cluster": {
        "type": "string",
        "description": "Optional: the Kubernetes cluster (context name) to query; the call runs on the connection "
                       "bound to it.",
    }},
    default_key_fields=("k8s_context",),
    unscoped=UNSCOPED_SINGLE,
    named_drops=("kubeconfig_path", "k8s_context", "k8s_use_kubectl", "kubectl_path", "kubectl_container_path",
                 "k8s_namespace"),
    tool_names=frozenset({"kubernetes_topology_snapshot", RUN_KUBECTL}),
    complete=_complete,
    runtime_guard=_runtime_guard,
    request_guard=_request_guard,
)

__all__ = ["KUBERNETES"]
